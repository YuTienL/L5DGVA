"""dv_harness/syoscb_source_audit.py -- SYOSCB-1 (REQUIRED SOURCE DIRECTORY
AUDIT) and SYOSCB-3 (KNOWLEDGE CENTER REGISTRATION), as real read-only
machinery instead of a one-off report an agent typed by hand.

WHAT THIS IS
------------
SYOSCB-1 names sixteen things that must be established about the real
`uvm_syoscb-1.0.2.4` tree BEFORE anything is planned on top of it -- package
files, scoreboard/configuration/queue classes, producer APIs, subscriber/TLM
structure, compare algorithms, macros, tests, examples, scripts, docs, compile
order, UVM dependency, license/copyright/provenance, version metadata -- and
then says, in its own words, "Do not rely only on this prompt's description."
This module answers all sixteen by READING the tree, so the answer is
reproducible by anyone who runs it rather than trusted from a transcript.

SYOSCB-3 then asks that the component be registered in the EXISTING Knowledge
Center -- "Do not create a parallel knowledge store." So the registration half
here is only a PAYLOAD BUILDER: it fills
`knowledge_center.THIRD_PARTY_COMPONENT_FIELDS` from this audit's real
findings and hands the dict back. Publishing it is
`KnowledgeCenterClient.record_component()`, which is the same `add` verb, the
same broker, the same shard lifecycle every other shared record already uses.
Nothing in this module opens a socket.

WHAT IT REUSES RATHER THAN REBUILDS
-----------------------------------
  * `vip_symbol_index.index_source_text()` / `iter_source_files()` is the ONLY
    SystemVerilog class scanner used here -- the same one `amba_scoreboard_env`
    uses, and for the same reason: it retains DECLARATIONS AND LOCATIONS ONLY
    and never a method body (`assert_no_bodies_retained()`), which is what
    makes reading a third-party tree we must not absorb structurally safe
    rather than merely promised.
  * `connectivity.BindTier` is the ONLY confidence vocabulary. A class role
    read off a real `extends` chain is T2_STRUCTURAL_MATCH; one resting on a
    class NAME token is T3_NAMING_HEURISTIC and can never be auto-accepted.
  * `connectivity.REQUIRED_HUMAN_INPUT` is the sentinel for every field the
    tree genuinely cannot settle (an L5 destination path, for instance, is a
    Phase-2 decision no amount of reading upstream can produce).
  * `connectivity.render_markdown_table()` renders every table.
  * `amba_scoreboard_env.InspectedFile` is the read-only-proof record, reused
    so "which files did we read, and were they unchanged afterwards" has one
    shape in this repo rather than two.

THE HARD BOUNDARY THIS MODULE ENFORCES
--------------------------------------
The upstream tree is inspectable read-only RIGHT NOW; vendoring it into this
repository is SYOSCB-2/SYOSCB-34, i.e. only after the SYOSCB-33 human review
gate. Two assertions make that checkable instead of promised:
`assert_source_unmodified()` (nothing we did wrote to upstream) and
`assert_not_vendored()` (no upstream file has appeared inside this repository,
by directory name OR by content digest). No SystemVerilog is emitted anywhere
in this module, and `assert_no_emittable_sv()` proves that of every artifact it
renders.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dv_harness import vip_symbol_index
from dv_harness.amba_scoreboard_env import InspectedFile
from dv_harness.connectivity import (
    ConnectivityError,
    REQUIRED_HUMAN_INPUT,
    BindTier,
    render_markdown_table,
)
from dv_harness.knowledge_center import (
    THIRD_PARTY_COMPONENT_FIELDS,
    THIRD_PARTY_COMPONENT_KIND,
)


class SyoscbSourceAuditError(ConnectivityError):
    """A source root that does not exist, an upstream file changed underneath
    a read-only audit, or upstream content found vendored into this repository
    before the Phase-2 gate allowed it. Subclasses `ConnectivityError` so a
    caller already handling this pipeline's errors handles these too."""


# ===========================================================================
# SYOSCB-1's own sixteen checklist items
# ===========================================================================

#: The audit item is answered from the tree.
AUDIT_FOUND = "FOUND"
#: The audit item is genuinely absent from the tree. A finding, not an error --
#: a library with no vendor scripts is a real fact about that library.
AUDIT_NOT_FOUND = "NOT_FOUND"

#: SYOSCB-1's list, verbatim in order, as stable keys. Kept as a tuple so a
#: report cannot silently answer fifteen of sixteen: `audit_checklist()`
#: returns an entry for every one of these or raises.
AUDIT_ITEMS: tuple = (
    "package_files",
    "scoreboard_classes",
    "configuration_classes",
    "queue_implementations",
    "producer_apis",
    "subscriber_tlm_structure",
    "compare_algorithms",
    "macros",
    "tests",
    "examples",
    "scripts",
    "documentation",
    "compile_order",
    "uvm_dependencies",
    "license_copyright_provenance",
    "version_metadata",
)


# ===========================================================================
# Class roles inside the upstream tree
# ===========================================================================

ROLE_SCOREBOARD_CORE = "SCOREBOARD_CORE"
ROLE_CONFIGURATION = "CONFIGURATION"
ROLE_QUEUE = "QUEUE"
ROLE_QUEUE_ITERATOR = "QUEUE_ITERATOR"
ROLE_COMPARE_STRATEGY = "COMPARE_STRATEGY"
ROLE_SUBSCRIBER = "SUBSCRIBER"
ROLE_ITEM_WRAPPER = "ITEM_WRAPPER"
ROLE_REPORT_CATCHER = "REPORT_CATCHER"
ROLE_UNCLASSIFIED = "UNCLASSIFIED"

ROLE_VALUES: tuple = (
    ROLE_SCOREBOARD_CORE, ROLE_CONFIGURATION, ROLE_QUEUE, ROLE_QUEUE_ITERATOR,
    ROLE_COMPARE_STRATEGY, ROLE_SUBSCRIBER, ROLE_ITEM_WRAPPER,
    ROLE_REPORT_CATCHER, ROLE_UNCLASSIFIED,
)

#: UVM base class -> role. Deriving a role from these is a STRUCTURAL fact
#: (T2): the source really says `extends uvm_scoreboard`, and no name was
#: consulted to reach that conclusion.
STRUCTURAL_ROLE_BY_UVM_BASE: dict = {
    "uvm_scoreboard": ROLE_SCOREBOARD_CORE,
    "uvm_subscriber": ROLE_SUBSCRIBER,
    "uvm_report_catcher": ROLE_REPORT_CATCHER,
}

#: Name token -> role, checked IN ORDER. Always T3: `cl_syoscb_queue extends
#: uvm_component` is a queue by convention only, and this project's Bind-Tier
#: rule ("T3 ALWAYS requires human confirmation, NEVER auto-accepted") applies
#: to a class role exactly as it does to a bind candidate. `iterator` precedes
#: `queue` because `cl_syoscb_queue_iterator_base` carries both tokens and is
#: an iterator, not a queue.
NAMING_ROLE_HINTS: tuple = (
    ("iterator", ROLE_QUEUE_ITERATOR),
    ("compare", ROLE_COMPARE_STRATEGY),
    ("queue", ROLE_QUEUE),
    ("cfg", ROLE_CONFIGURATION),
    ("config", ROLE_CONFIGURATION),
    ("item", ROLE_ITEM_WRAPPER),
)


# ===========================================================================
# Ordering semantics, in L5's own vocabulary
# ===========================================================================
#
# `connectivity.SCOREBOARD_PLAN_FIELDS` already owns an `ordering` field on the
# protocol-agnostic scoreboard plan. These are the values that field can take
# that SyoSil can actually implement, so a plan says "ordering:
# IN_ORDER_PER_PRODUCER" and this module answers "that is
# `cl_syoscb_compare_iop`, declared at src/cl_syoscb_compare_iop.svh:20" --
# rather than a second ordering vocabulary being invented next to the first.

ORDERING_IN_ORDER = "IN_ORDER"
ORDERING_IN_ORDER_PER_PRODUCER = "IN_ORDER_PER_PRODUCER"
ORDERING_OUT_OF_ORDER = "OUT_OF_ORDER"

ORDERING_VALUES: tuple = (
    ORDERING_IN_ORDER, ORDERING_IN_ORDER_PER_PRODUCER, ORDERING_OUT_OF_ORDER,
)

#: Class-name suffix -> ordering. Checked longest-first so `_iop` is never
#: mistaken for `_io`.
_COMPARE_SUFFIX_TO_ORDERING: tuple = (
    ("_ooo", ORDERING_OUT_OF_ORDER),
    ("_iop", ORDERING_IN_ORDER_PER_PRODUCER),
    ("_io", ORDERING_IN_ORDER),
)


# ===========================================================================
# File-classification vocabulary
# ===========================================================================

SV_SUFFIXES: tuple = (".sv", ".svh", ".v", ".vh")
SCRIPT_SUFFIXES: tuple = (".mk", ".sh", ".csh", ".tcl", ".py", ".pl")
SCRIPT_NAME_PREFIXES: tuple = ("makefile",)
DOC_SUFFIXES: tuple = (".pdf", ".html", ".htm", ".md", ".txt", ".css")
TEST_DIR_NAMES: frozenset = frozenset({"test", "tests"})
EXAMPLE_DIR_NAMES: frozenset = frozenset({"tb", "example", "examples"})

_UVM_MACRO_RE = re.compile(r"`(uvm_[a-z0-9_]+)")
_IFDEF_RE = re.compile(r"`(?:ifn?def|elsif)\s+([A-Za-z_]\w*)")
_INCLUDE_RE = re.compile(r'^\s*`include\s+"([^"]+)"')
_PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z_]\w*)\s*;")
_UVM_VERSION_RE = re.compile(r"^\s*UVM_VERSION\s*\??=\s*(\S+)")
_COPYRIGHT_RE = re.compile(r"(Copyright\s+.+)$", re.IGNORECASE)


@dataclass
class SyoscbSourceAudit:
    """SYOSCB-1's complete read-only result for one upstream source tree."""
    root: str
    files: list                       # list[InspectedFile], EVERY file under root
    version: str
    version_evidence: str
    license: dict
    package: dict
    classes: list                     # list[dict]: name/base_class/file/line/role/tier/...
    compare_algorithms: dict          # ordering value -> {class, file, line}
    macros: dict                      # {"uvm": [...], "conditional_compile": [...]}
    producer_apis: list               # list[dict]: class/method/arguments/file/line
    analysis_ports: list              # list[dict]: class/name/kind/direction/file/line
    tests: list                       # list[str], repo-relative
    examples: list
    scripts: list
    documentation: list
    known_limitations: list
    uvm_dependency: dict

    def classes_with_role(self, role: str) -> list:
        return [c for c in self.classes if c["role"] == role]

    def class_named(self, name: str) -> Optional[dict]:
        return next((c for c in self.classes if c["name"] == name), None)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "file_count": len(self.files),
            "inspected_files": [f.to_dict() for f in self.files],
            "version": self.version,
            "version_evidence": self.version_evidence,
            "license": dict(self.license),
            "package": dict(self.package),
            "classes": [dict(c) for c in self.classes],
            "compare_algorithms": dict(self.compare_algorithms),
            "macros": dict(self.macros),
            "producer_apis": [dict(p) for p in self.producer_apis],
            "analysis_ports": [dict(a) for a in self.analysis_ports],
            "tests": list(self.tests),
            "examples": list(self.examples),
            "scripts": list(self.scripts),
            "documentation": list(self.documentation),
            "known_limitations": list(self.known_limitations),
            "uvm_dependency": dict(self.uvm_dependency),
            "checklist": audit_checklist(self),
        }


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:  # pragma: no cover - a path outside root cannot occur here
        return str(path).replace("\\", "/")


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    if any(p.lower() in TEST_DIR_NAMES for p in parts[:-1]):
        return True
    stem = parts[-1].lower()
    return "_test_" in stem or stem.startswith("test_") or "_test." in stem


def _is_script(rel: str) -> bool:
    name = rel.split("/")[-1].lower()
    if any(name.startswith(p) for p in SCRIPT_NAME_PREFIXES):
        return True
    return any(name.endswith(s) for s in SCRIPT_SUFFIXES)


def _is_doc(rel: str) -> bool:
    name = rel.split("/")[-1].lower()
    return any(name.endswith(s) for s in DOC_SUFFIXES)


def _resolve_role(entry: dict, by_name: dict, resolved: dict) -> dict:
    """One class's role, structural evidence preferred over naming evidence.

    Three routes, in descending confidence:
      1. the class extends a UVM base whose role is unambiguous (T2);
      2. the class extends another class IN THIS TREE that already has a role,
         so the role is inherited from a real `extends` edge (T2) -- this is
         what makes `cl_syoscb_queue_std` a queue on structure rather than on
         its name;
      3. a token in the class NAME (T3) -- never auto-accepted.
    A class none of the three settles is UNCLASSIFIED at T4, not guessed."""
    base = entry.get("base_class") or ""
    if base in STRUCTURAL_ROLE_BY_UVM_BASE:
        return {"role": STRUCTURAL_ROLE_BY_UVM_BASE[base],
                "tier": BindTier.T2_STRUCTURAL_MATCH.value,
                "evidence": f"{entry['file']}:{entry['line']} extends {base}"}

    if base in by_name:
        parent = resolved.get(base)
        if parent is None:
            parent = _resolve_role(by_name[base], by_name, resolved)
            resolved[base] = parent
        if parent["role"] != ROLE_UNCLASSIFIED:
            return {"role": parent["role"],
                    "tier": BindTier.T2_STRUCTURAL_MATCH.value,
                    "evidence": (f"{entry['file']}:{entry['line']} extends {base}, "
                                 f"whose role is {parent['role']} ({parent['evidence']})")}

    lowered = entry["name"].lower()
    for token, role in NAMING_ROLE_HINTS:
        if token in lowered:
            return {"role": role,
                    "tier": BindTier.T3_NAMING_HEURISTIC.value,
                    "evidence": (f"{entry['file']}:{entry['line']} class name contains "
                                 f"'{token}'; base class is "
                                 f"{base or '(none)'}, which does not establish the role")}

    return {"role": ROLE_UNCLASSIFIED,
            "tier": BindTier.T4_UNDECIDABLE.value,
            "evidence": (f"{entry['file']}:{entry['line']} neither the base class "
                         f"({base or '(none)'}) nor the class name establishes a role")}


def _parse_known_limitations(text: str) -> list:
    """The numbered items under RELEASE_NOTES' "Known Limitations" heading.

    Upstream's own heading is misspelled ("Know Limitations" in 1.0.2.4), so
    the match is on the distinctive word `Limitations` inside a `[n]:` section
    heading rather than on an exact phrase -- a parser that only matched the
    correct spelling would report this real, present section as absent."""
    lines = text.splitlines()
    out: list = []
    inside = False
    current: Optional[str] = None
    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip("# ").strip()
        if re.match(r"^\[\d+\]\s*:", stripped):
            if inside and current:
                out.append(current.strip())
                current = None
            inside = "limitation" in stripped.lower()
            continue
        if not inside:
            continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            if current:
                out.append(current.strip())
            current = m.group(1).strip()
        elif current is not None and line.strip():
            current += " " + line.strip()
        elif current:
            out.append(current.strip())
            current = None
    if inside and current:
        out.append(current.strip())
    return out


def audit_syoscb_source(root) -> SyoscbSourceAudit:
    """SYOSCB-1's audit pass over the real upstream tree. Reads; never writes.

    `root` is the upstream source directory (the real one is
    `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`). A root that does not exist RAISES
    rather than returning an empty audit: a mistyped path must never be
    indistinguishable from a library with nothing in it, since the second is a
    finding a reviewer would act on and the first is an operator error."""
    base = Path(root)
    if not base.is_dir():
        raise SyoscbSourceAuditError("SYOSCB_SOURCE_ROOT_NOT_FOUND", {
            "root": str(root),
            "hint": "SYOSCB-1 audits the real upstream tree read-only; a missing root is "
                    "an operator error, never an empty library"})

    inspected: list = []
    rel_paths: list = []
    for path in sorted(base.rglob("*"), key=lambda p: str(p).replace("\\", "/")):
        if not path.is_file():
            continue
        blob = path.read_bytes()
        rel = _rel(path, base)
        rel_paths.append(rel)
        inspected.append(InspectedFile(path=str(path).replace("\\", "/"),
                                       sha256=_sha256_bytes(blob), bytes=len(blob)))

    sv_files = [p for p in rel_paths if p.lower().endswith(SV_SUFFIXES)]
    texts = {rel: (base / rel).read_text(encoding="utf-8", errors="replace")
             for rel in rel_paths if rel.lower().endswith(SV_SUFFIXES + (".txt", ".mk"))
             or _is_script(rel)}

    classes: list = []
    for rel in sv_files:
        classes.extend(vip_symbol_index.index_source_text(texts[rel], rel))
    classes.sort(key=lambda c: (c["file"], c["line"]))
    # The no-body invariant is asserted on the scanned result too: this module
    # never writes an index file, so vip_symbol_index's own save-path assertion
    # would otherwise never run over an upstream tree we must not absorb.
    vip_symbol_index.assert_no_bodies_retained({"classes": classes})

    by_name = {c["name"]: c for c in classes}
    resolved: dict = {}
    enriched: list = []
    for entry in classes:
        info = resolved.get(entry["name"]) or _resolve_role(entry, by_name, resolved)
        resolved[entry["name"]] = info
        enriched.append({
            "name": entry["name"], "base_class": entry.get("base_class"),
            "file": entry["file"], "line": entry["line"],
            "role": info["role"], "tier": info["tier"], "evidence": info["evidence"],
            "api": [{"name": m["name"], "kind": m["kind"],
                     "return_type": m.get("return_type"),
                     "arguments": m.get("arguments"),
                     "file": m["file"], "line": m["line"]}
                    for m in entry.get("methods", [])],
        })

    version, version_evidence = _read_version(base, texts)
    package = _read_package(base, sv_files, texts)
    license_info = _read_license(base, texts)
    compare = _compare_algorithms(enriched)
    macros = _collect_macros(sv_files, texts)
    producers = _producer_apis(enriched)
    ports = _analysis_ports(classes, resolved)
    release_notes = texts.get("RELEASE_NOTES.txt", "")

    return SyoscbSourceAudit(
        root=str(base).replace("\\", "/"),
        files=inspected,
        version=version,
        version_evidence=version_evidence,
        license=license_info,
        package=package,
        classes=enriched,
        compare_algorithms=compare,
        macros=macros,
        producer_apis=producers,
        analysis_ports=ports,
        tests=[p for p in rel_paths if _is_test_path(p)],
        examples=[p for p in rel_paths
                  if not _is_test_path(p)
                  and any(seg.lower() in EXAMPLE_DIR_NAMES for seg in p.split("/")[:-1])],
        scripts=[p for p in rel_paths if _is_script(p)],
        documentation=[p for p in rel_paths if _is_doc(p)],
        known_limitations=_parse_known_limitations(release_notes),
        uvm_dependency=_uvm_dependency(package, rel_paths, texts),
    )


def _read_version(base: Path, texts: dict) -> tuple:
    """The version, from a VERSION file's first non-comment, non-blank line.

    Upstream's VERSION.txt carries an 18-line Apache header above the single
    line that is actually the version, so "first line" would report a `#####`
    banner as the version number."""
    for candidate in ("VERSION.txt", "VERSION", "version.txt"):
        text = texts.get(candidate)
        if text is None and (base / candidate).is_file():
            text = (base / candidate).read_text(encoding="utf-8", errors="replace")
        if text is None:
            continue
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            return line, f"{candidate}:{lineno}"
    return REQUIRED_HUMAN_INPUT, ""


def _read_package(base: Path, sv_files: list, texts: dict) -> dict:
    """The package compile unit and its `` `include `` order.

    SYOSCB-1 asks for "compile order" as a distinct item from "package files"
    because in this library they are the same fact: only the package file is
    fed to the compiler and every other file reaches it through an include, so
    the include sequence IS the compile order. Reporting the include list in
    source order rather than sorted is the whole point."""
    for rel in sv_files:
        text = texts[rel]
        m = None
        for lineno, raw in enumerate(text.splitlines(), start=1):
            m = _PACKAGE_RE.match(raw)
            if m:
                break
        if not m:
            continue
        includes = [(im.group(1), n)
                    for n, raw in enumerate(text.splitlines(), start=1)
                    if (im := _INCLUDE_RE.match(raw))]
        return {
            "name": m.group(1),
            "file": rel,
            "line": lineno,
            "compile_order": [inc for inc, _ in includes if inc != "uvm_macros.svh"],
            "compile_order_evidence": [f"{rel}:{n}" for inc, n in includes
                                       if inc != "uvm_macros.svh"],
            "imports_uvm_pkg": bool(re.search(r"^\s*import\s+uvm_pkg\s*::", text, re.M)),
            "includes_uvm_macros": "uvm_macros.svh" in [inc for inc, _ in includes],
        }
    return {"name": REQUIRED_HUMAN_INPUT, "file": "", "line": 0, "compile_order": [],
            "compile_order_evidence": [], "imports_uvm_pkg": False,
            "includes_uvm_macros": False}


def _read_license(base: Path, texts: dict) -> dict:
    """License identity and copyright holder, both cited to a real line.

    The SPDX id is only asserted when the license text names BOTH "Apache
    License" and "Version 2.0"; anything else reports UNIDENTIFIED with the
    file still cited, because a wrong SPDX id on a redistributable dependency
    is worse than an honest "a human must read this"."""
    out = {"license_file": "", "spdx_id": REQUIRED_HUMAN_INPUT,
           "copyright": REQUIRED_HUMAN_INPUT, "copyright_evidence": "",
           "notice_file": ""}
    for candidate in ("LICENSE.txt", "LICENSE", "COPYING"):
        path = base / candidate
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        out["license_file"] = candidate
        if "Apache License" in text and "Version 2.0" in text:
            out["spdx_id"] = "Apache-2.0"
        else:
            out["spdx_id"] = "UNIDENTIFIED_LICENSE_TEXT"
        break

    for candidate in ("NOTICE.txt", "NOTICE", "LICENSE.txt", "VERSION.txt"):
        path = base / candidate
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, raw in enumerate(text.splitlines(), start=1):
            m = _COPYRIGHT_RE.search(raw.strip().lstrip("#").strip())
            if m and not m.group(1).lower().startswith("copyright [yyyy]"):
                out["copyright"] = m.group(1).strip()
                out["copyright_evidence"] = f"{candidate}:{lineno}"
                if candidate.startswith("NOTICE"):
                    out["notice_file"] = candidate
                break
        if out["copyright"] != REQUIRED_HUMAN_INPUT:
            break
    return out


def _compare_algorithms(classes: list) -> dict:
    """Ordering value -> the upstream class that implements it.

    SYOSCB-17 names three ordering concepts; this resolves each to a real class
    declaration or leaves it out. An ordering with no class is reported by
    `unresolved_orderings()` rather than silently defaulting to another
    algorithm, because silently comparing an out-of-order stream in order is
    the single most expensive substitution this layer could make."""
    out: dict = {}
    for entry in classes:
        if entry["role"] != ROLE_COMPARE_STRATEGY:
            continue
        lowered = entry["name"].lower()
        for suffix, ordering in _COMPARE_SUFFIX_TO_ORDERING:
            if lowered.endswith(suffix):
                out[ordering] = {"class": entry["name"], "file": entry["file"],
                                 "line": entry["line"], "base_class": entry["base_class"],
                                 "tier": entry["tier"]}
                break
    return out


def unresolved_orderings(audit: SyoscbSourceAudit) -> list:
    """Every ordering value in `ORDERING_VALUES` the tree supplies no compare
    class for. An empty list means all three are real and citable."""
    return [o for o in ORDERING_VALUES if o not in audit.compare_algorithms]


def compare_class_for_ordering(audit: SyoscbSourceAudit, ordering: str) -> dict:
    """The bridge from `connectivity.SCOREBOARD_PLAN_FIELDS`' `ordering` field
    to a real upstream class. An unknown ordering value RAISES (it is a caller
    bug, not a missing fact); a known one the tree does not implement returns
    `REQUIRED_HUMAN_INPUT` with the reason, so a plan cannot quietly acquire an
    ordering nothing can execute."""
    if ordering not in ORDERING_VALUES:
        raise SyoscbSourceAuditError("UNKNOWN_ORDERING_VALUE", {
            "ordering": ordering, "known": list(ORDERING_VALUES)})
    hit = audit.compare_algorithms.get(ordering)
    if hit:
        return dict(hit)
    return {"class": REQUIRED_HUMAN_INPUT,
            "reason": "NO_UPSTREAM_COMPARE_CLASS_FOR_THIS_ORDERING",
            "hint": f"{audit.root} declares no compare class implementing {ordering}; "
                    "an L5 scoreboard plan asking for it needs either an upstream "
                    "extension or a different ordering, decided by a human"}


def _collect_macros(sv_files: list, texts: dict) -> dict:
    """SYOSCB-1's "macros" item: which UVM macros and which conditional-compile
    symbols this library uses.

    This is the ONE place that scans a whole file rather than only declaration
    lines, because a macro invocation can legitimately sit inside a method body
    and the answer to "does this library use `` `uvm_fatal ``" would otherwise
    be wrong. What it retains is bounded to the IDENTIFIER -- the regex captures
    `[a-z0-9_]+` after the backtick and stops, so no argument list, no message
    string and no surrounding statement can come along with it. That keeps the
    module's no-body-text property intact while still answering the item."""
    uvm: set = set()
    conditional: set = set()
    for rel in sv_files:
        text = texts[rel]
        uvm.update(_UVM_MACRO_RE.findall(text))
        conditional.update(_IFDEF_RE.findall(text))
    return {"uvm": sorted(uvm), "conditional_compile": sorted(conditional)}


def _producer_apis(classes: list) -> list:
    """Every declared method whose NAME or ARGUMENT LIST mentions a producer.

    SyoSil's producer concept is not a class -- it is a string threaded through
    `add_item(queue_name, producer, item)` and the config's producer/queue map.
    So the honest answer to SYOSCB-1's "producer APIs" is the set of real
    declarations that carry it, cited to file:line, not a class name."""
    out: list = []
    for entry in classes:
        for method in entry["api"]:
            haystack = f"{method['name']} {method.get('arguments') or ''}".lower()
            if "producer" not in haystack:
                continue
            out.append({"class": entry["name"], "method": method["name"],
                        "kind": method["kind"],
                        "return_type": method.get("return_type"),
                        "arguments": method.get("arguments"),
                        "file": method["file"], "line": method["line"]})
    return out


def _analysis_ports(classes: list, resolved: dict) -> list:
    out: list = []
    for entry in classes:
        for port in entry.get("analysis_ports", []):
            out.append({"class": entry["name"],
                        "role": resolved[entry["name"]]["role"],
                        "name": port["name"], "port_type": port["port_type"],
                        "kind": port["kind"], "direction": port["direction"],
                        "transaction_type": port.get("transaction_type"),
                        "file": port["file"], "line": port["line"]})
    return out


def _uvm_dependency(package: dict, rel_paths: list, texts: dict) -> dict:
    """Whether the library requires UVM, and which version its own build
    scripts name. The version comes from a build script's real assignment, not
    from a release-notes prose sentence -- prose says what was tested, the
    script says what will actually be compiled against."""
    evidence: list = []
    version = REQUIRED_HUMAN_INPUT
    for rel in rel_paths:
        if not _is_script(rel) or rel not in texts:
            continue
        for lineno, raw in enumerate(texts[rel].splitlines(), start=1):
            m = _UVM_VERSION_RE.match(raw)
            if m:
                version = m.group(1)
                evidence.append(f"{rel}:{lineno}")
                break
        if version != REQUIRED_HUMAN_INPUT:
            break
    requires = bool(package.get("imports_uvm_pkg") or package.get("includes_uvm_macros"))
    if requires and package.get("file"):
        evidence.append(f"{package['file']}:{package['line']} package {package['name']}")
    return {"requires_uvm": requires, "uvm_version": version, "evidence": evidence}


def audit_checklist(audit: SyoscbSourceAudit) -> dict:
    """SYOSCB-1's sixteen items, each answered FOUND/NOT_FOUND with real
    evidence. Every key in `AUDIT_ITEMS` is present in the result, so a report
    rendered from this cannot silently omit an item it failed to answer."""
    pkg = audit.package
    scoreboards = audit.classes_with_role(ROLE_SCOREBOARD_CORE)
    configs = audit.classes_with_role(ROLE_CONFIGURATION)
    queues = audit.classes_with_role(ROLE_QUEUE)
    iterators = audit.classes_with_role(ROLE_QUEUE_ITERATOR)
    subscribers = audit.classes_with_role(ROLE_SUBSCRIBER)

    def entry(items, evidence) -> dict:
        return {"status": AUDIT_FOUND if items else AUDIT_NOT_FOUND,
                "count": len(items), "evidence": evidence}

    def cited(rows) -> list:
        return [f"{c['name']} ({c['file']}:{c['line']})" for c in rows]

    out = {
        "package_files": entry(
            [pkg["file"]] if pkg.get("file") else [],
            [f"{pkg['file']}:{pkg['line']} package {pkg['name']}"] if pkg.get("file") else []),
        "scoreboard_classes": entry(scoreboards, cited(scoreboards)),
        "configuration_classes": entry(configs, cited(configs)),
        "queue_implementations": entry(queues + iterators, cited(queues + iterators)),
        "producer_apis": entry(audit.producer_apis,
                               [f"{p['class']}::{p['method']} ({p['file']}:{p['line']})"
                                for p in audit.producer_apis]),
        "subscriber_tlm_structure": entry(
            subscribers + audit.analysis_ports,
            cited(subscribers) + [f"{a['class']}.{a['name']} {a['port_type']} "
                                  f"({a['file']}:{a['line']})" for a in audit.analysis_ports]),
        "compare_algorithms": entry(
            list(audit.compare_algorithms),
            [f"{k} -> {v['class']} ({v['file']}:{v['line']})"
             for k, v in sorted(audit.compare_algorithms.items())]),
        "macros": entry(audit.macros["uvm"] + audit.macros["conditional_compile"],
                        audit.macros["uvm"] + audit.macros["conditional_compile"]),
        "tests": entry(audit.tests, list(audit.tests)),
        "examples": entry(audit.examples, list(audit.examples)),
        "scripts": entry(audit.scripts, list(audit.scripts)),
        "documentation": entry(audit.documentation, list(audit.documentation)),
        "compile_order": entry(pkg.get("compile_order") or [],
                               list(pkg.get("compile_order_evidence") or [])),
        "uvm_dependencies": entry(
            audit.uvm_dependency["evidence"] if audit.uvm_dependency["requires_uvm"] else [],
            list(audit.uvm_dependency["evidence"])),
        "license_copyright_provenance": entry(
            [v for v in (audit.license["license_file"], audit.license["copyright"])
             if v and v != REQUIRED_HUMAN_INPUT],
            [f"{audit.license['license_file']} -> {audit.license['spdx_id']}"]
            + ([audit.license["copyright_evidence"]]
               if audit.license["copyright_evidence"] else [])),
        "version_metadata": entry(
            [] if audit.version == REQUIRED_HUMAN_INPUT else [audit.version],
            [audit.version_evidence] if audit.version_evidence else []),
    }
    missing = [k for k in AUDIT_ITEMS if k not in out]
    if missing:  # pragma: no cover - guards a future edit, not a runtime path
        raise SyoscbSourceAuditError("AUDIT_CHECKLIST_INCOMPLETE", {
            "missing_items": missing,
            "hint": "SYOSCB-1 names sixteen items; a checklist that answers fewer is "
                    "not an answer to it"})
    return {k: out[k] for k in AUDIT_ITEMS}


def unanswered_audit_items(audit: SyoscbSourceAudit) -> list:
    """The checklist items this tree genuinely does not answer. Reported so a
    NOT_FOUND is a visible finding rather than an empty table cell."""
    return [k for k, v in audit_checklist(audit).items() if v["status"] != AUDIT_FOUND]


# ===========================================================================
# The two read-only / not-yet-vendored assertions
# ===========================================================================

def assert_source_unmodified(audit: SyoscbSourceAudit) -> None:
    """"Inspect, do not modify" as a CHECKABLE property.

    Re-reads every audited file and compares its sha256 against the digest
    recorded at audit time. A file that moved, vanished or changed raises. The
    upstream tree is a third-party dependency this repository does not own; a
    change under it during a read-only audit means something wrote to somebody
    else's source."""
    for item in audit.files:
        path = Path(item.path)
        if not path.exists():
            raise SyoscbSourceAuditError("SYOSCB_SOURCE_DISAPPEARED_DURING_AUDIT", {
                "path": item.path,
                "hint": "SYOSCB-1 is read-only; a file audited at the start must still "
                        "be there at the end"})
        if _sha256_bytes(path.read_bytes()) != item.sha256:
            raise SyoscbSourceAuditError("SYOSCB_SOURCE_MODIFIED_DURING_AUDIT", {
                "path": item.path, "sha256_at_audit": item.sha256,
                "sha256_now": _sha256_bytes(path.read_bytes()),
                "hint": "the upstream tree must never be written to; SYOSCB-4 forbids "
                        "even a fork without a recorded reason, and an audit is not one"})


#: Directory/file name prefix that means an upstream tree has been copied in.
VENDORED_NAME_PREFIX = "uvm_syoscb"

#: Never walked when checking a repository for vendored upstream content --
#: build/VCS noise, not source anyone vendored on purpose.
_SKIP_DIRS: frozenset = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules",
                                   ".venv", "venv", ".mypy_cache"})


#: Where a real SYOSCB-33 human approval of vendoring is recorded, relative to
#: a project root. A JSON object; see `load_vendoring_approval()`.
VENDORING_APPROVAL_FILENAME = "dv_harness/syoscb_vendoring_approval.json"


def load_vendoring_approval(repo_root) -> Optional[dict]:
    """Reads the real, on-disk SYOSCB-33 approval record if one exists --
    never invented, never assumed. Returns `None` (not an empty dict) when no
    approval file is present, so "nobody approved this" and "an approval
    exists but is malformed" stay distinguishable to a caller. A present but
    malformed (non-JSON, or missing `approved`/`l5_destination`) file raises
    `SyoscbSourceAuditError` rather than being silently ignored -- a broken
    approval record must never be read as "no approval", which would make
    `assert_not_vendored()` MORE permissive on a parse failure than on a
    missing file."""
    path = Path(repo_root) / VENDORING_APPROVAL_FILENAME
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SyoscbSourceAuditError("SYOSCB_VENDORING_APPROVAL_UNREADABLE", {
            "path": str(path), "error": str(exc)}) from exc
    if not isinstance(record, dict) or "approved" not in record or "l5_destination" not in record:
        raise SyoscbSourceAuditError("SYOSCB_VENDORING_APPROVAL_MALFORMED", {
            "path": str(path),
            "hint": "an approval record must be a JSON object carrying at least "
                    "'approved' and 'l5_destination'"})
    return record


def assert_not_vendored(repo_root, audit: Optional[SyoscbSourceAudit] = None,
                         approval: Optional[dict] = None) -> dict:
    """SYOSCB-2/SYOSCB-33's boundary, enforced rather than promised: no
    upstream file may be inside this repository UNLESS it sits under a real,
    recorded SYOSCB-33 human approval's own `l5_destination` -- an unapproved
    copy anywhere else is still refused exactly as before.

    Two independent detectors, because either alone is evadable:
      * a path segment named like the upstream tree (`uvm_syoscb...`) -- catches
        a copy even if every file inside it was then edited;
      * a CONTENT digest match against the audit's own file hashes -- catches a
        copy that was renamed, which the name check would miss entirely.
    The content check is cheap: only a file whose (basename, size) already
    matches an audited file is ever hashed.

    `approval`, if supplied, must be a record shaped like
    `load_vendoring_approval()`'s return value with `approved: true` -- a
    falsy/absent `approved` field means the record is on file but does NOT
    authorize anything (e.g. a revoked or draft approval), so a hit under its
    `l5_destination` is still reported, never silently allowed. Passing no
    `approval` preserves the original all-or-nothing behaviour exactly, so
    every existing caller is unaffected.

    Returns the evidence dict (an approved hit's own relative path is listed
    under `approved_vendored`, always reported, never hidden by being
    excused) on a repository with no UNAPPROVED upstream file; raises
    `SyoscbSourceAuditError` naming the offending paths otherwise. Passing no
    audit runs the name check alone, which is still a real check -- it just
    cannot see a renamed copy, and the result says so."""
    root = Path(repo_root)
    if not root.is_dir():
        raise SyoscbSourceAuditError("REPO_ROOT_NOT_FOUND", {"repo_root": str(repo_root)})

    approved_prefix = None
    if approval and approval.get("approved") and approval.get("l5_destination"):
        approved_prefix = Path(approval["l5_destination"])
        if not approved_prefix.is_absolute():
            approved_prefix = (root / approved_prefix).resolve()

    def _is_approved(path: Path) -> bool:
        if approved_prefix is None:
            return False
        try:
            path.resolve().relative_to(approved_prefix)
        except ValueError:
            return False
        return True

    by_key: dict = {}
    if audit is not None:
        for item in audit.files:
            by_key.setdefault((Path(item.path).name.lower(), item.bytes), set()).add(item.sha256)

    name_hits: list = []
    content_hits: list = []
    approved_hits: list = []
    scanned = 0
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if any(p in _SKIP_DIRS for p in parts):
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        if path.name.lower().startswith(VENDORED_NAME_PREFIX):
            (approved_hits if _is_approved(path) else name_hits).append(rel)
            continue
        if not by_key or not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:  # pragma: no cover - a vanishing temp file, not a finding
            continue
        digests = by_key.get((path.name.lower(), size))
        if not digests:
            continue
        scanned += 1
        if _sha256_bytes(path.read_bytes()) in digests:
            (approved_hits if _is_approved(path) else content_hits).append(rel)

    if name_hits or content_hits:
        raise SyoscbSourceAuditError("SYOSCB_UPSTREAM_VENDORED_BEFORE_APPROVAL", {
            "repo_root": str(root), "name_matches": sorted(name_hits),
            "content_matches": sorted(content_hits),
            "hint": "SYOSCB-2 vendoring is a PHASE-2 action gated by SYOSCB-33/34; nothing "
                    "may be copied out of the upstream tree before a human approves it, and "
                    "only the exact l5_destination a real approval record names is exempt"})
    return {"repo_root": str(root).replace("\\", "/"),
            "name_check": "CLEAN",
            "content_check": "CLEAN" if by_key else "NOT_RUN_NO_AUDIT_SUPPLIED",
            "candidate_files_hashed": scanned,
            "approved_vendored": sorted(approved_hits)}


#: A rendered artifact must never look like emittable SystemVerilog. Mirrors
#: `amba_fabric_discovery.assert_no_bind_statement()`'s reasoning: a planning
#: artifact that renders a `bind` or a `class ... extends` block is one
#: copy-paste away from becoming real testbench source nobody reviewed.
_EMITTABLE_SV_RE = re.compile(
    r"^\s*(?:bind\s+\w|class\s+\w+\s+extends\b|module\s+\w|package\s+\w+\s*;)", re.M)


def assert_no_emittable_sv(text: str, *, label: str = "artifact") -> None:
    """Raise if a rendered artifact contains a line that could be pasted into a
    `.sv` file and compiled. Class NAMES and `file:line` citations are fine --
    that is what an audit is for; a class DECLARATION or a bind is not."""
    hits = [m.group(0).strip() for m in _EMITTABLE_SV_RE.finditer(text)]
    if hits:
        raise SyoscbSourceAuditError("SYOSCB_ARTIFACT_CONTAINS_EMITTABLE_SV", {
            "label": label, "matches": hits[:8],
            "hint": "SYOSCB-33 forbids implementation before approval; an audit artifact "
                    "must cite upstream code, never restate it in compilable form"})


# ===========================================================================
# SYOSCB-3: the Knowledge Center registration PAYLOAD
# ===========================================================================

#: What SYOSCB-3's BUILD_STATUS must say while the SYOSCB-33 gate is closed.
#: SYOSCB-3's own wording is "UNKNOWN until tested"; this spells out WHY it is
#: unknown, since "nobody has compiled it" and "a compile failed" are different
#: facts a reader of the shared Knowledge Center must not confuse.
BUILD_STATUS_NOT_BUILT = "NOT_BUILT_PHASE_2_APPROVAL_REQUIRED"

DEFAULT_COMPONENT_ROLE = "AMBA SoC Bus Generic Scoreboard Core / Reference"
DEFAULT_INTEGRATION_POLICY = "REUSE + ENHANCE THROUGH ADAPTER / IR / PREDICTOR LAYERS"


#: Citations kept per checklist item inside a registration record. The audit
#: itself keeps all of them; a SHARED Knowledge Center record must not, because
#: this library's `documentation` item alone is 101 generated Doxygen pages and
#: a record nobody can read is a record nobody checks. The real total is kept
#: alongside the sample, so a truncated list can never be mistaken for the
#: whole set.
MAX_EVIDENCE_CITATIONS_PER_ITEM = 12


def _bounded_evidence(checklist: dict) -> dict:
    out: dict = {}
    for item, row in checklist.items():
        citations = list(row["evidence"])
        if len(citations) <= MAX_EVIDENCE_CITATIONS_PER_ITEM:
            out[item] = citations
        else:
            out[item] = {
                "sample": citations[:MAX_EVIDENCE_CITATIONS_PER_ITEM],
                "total": len(citations),
                "truncated": True,
            }
    return out


def build_component_registration_payload(
    audit: SyoscbSourceAudit, *,
    component: str = "uvm_syoscb",
    role: str = DEFAULT_COMPONENT_ROLE,
    integration_policy: str = DEFAULT_INTEGRATION_POLICY,
    l5_destination: Optional[str] = None,
    build_status: str = BUILD_STATUS_NOT_BUILT,
) -> dict:
    """SYOSCB-3's registration record, filled from THIS audit's real findings.

    Returns a plain dict keyed by `knowledge_center.THIRD_PARTY_COMPONENT_FIELDS`
    -- it performs NO transport of any kind. Publishing is a separate, explicit
    `KnowledgeCenterClient.record_component()` call on the existing shared
    store, which is what keeps SYOSCB-3's "Do not create a parallel knowledge
    store" true by construction: this module has no store.

    `l5_destination` is `REQUIRED_HUMAN_INPUT` unless a caller supplies one,
    because where the tree will live inside this repository is a SYOSCB-2
    decision that happens AFTER the SYOSCB-33 gate. Writing a plausible-looking
    path there today would publish a location nothing is at."""
    limitations = list(audit.known_limitations) or [REQUIRED_HUMAN_INPUT]
    provenance = {
        "license_file": audit.license["license_file"] or REQUIRED_HUMAN_INPUT,
        "spdx_id": audit.license["spdx_id"],
        "copyright": audit.license["copyright"],
        "copyright_evidence": audit.license["copyright_evidence"] or REQUIRED_HUMAN_INPUT,
        "version_evidence": audit.version_evidence or REQUIRED_HUMAN_INPUT,
        "audited_file_count": len(audit.files),
        "audited_root_sha256": audit_fingerprint(audit),
        "vendored_into_repository": False,
        "vendoring_gate": "SYOSCB-33 human review gate / SYOSCB-34 Phase 2",
    }
    payload = {
        "COMPONENT": component,
        "VERSION": audit.version,
        "SOURCE_REFERENCE": audit.root,
        "ROLE": role,
        "INTEGRATION_POLICY": integration_policy,
        "L5_DESTINATION": l5_destination or REQUIRED_HUMAN_INPUT,
        "BUILD_STATUS": build_status,
        "KNOWN_LIMITATIONS": limitations,
        "PROVENANCE": provenance,
        "UPSTREAM_DEPENDENCIES": audit.uvm_dependency,
        "EVIDENCE": _bounded_evidence(audit_checklist(audit)),
        "kind": THIRD_PARTY_COMPONENT_KIND,
    }
    unknown = set(payload) - set(THIRD_PARTY_COMPONENT_FIELDS) - {"kind"}
    if unknown:  # pragma: no cover - guards a future edit
        raise SyoscbSourceAuditError("REGISTRATION_PAYLOAD_UNKNOWN_FIELDS", {
            "unknown": sorted(unknown), "known": list(THIRD_PARTY_COMPONENT_FIELDS)})
    return payload


def audit_fingerprint(audit: SyoscbSourceAudit) -> str:
    """One digest over every audited file's (relative path, sha256), so two
    audits of "the same" upstream tree are comparable in a single field. Path
    is included, not just content: a file moved is a different tree."""
    root = Path(audit.root)
    h = hashlib.sha256()
    for item in sorted(audit.files, key=lambda f: f.path):
        h.update(_rel(Path(item.path), root).encode("utf-8"))
        h.update(b"\0")
        h.update(item.sha256.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def registration_blockers(payload: dict) -> list:
    """Every field in a registration payload still carrying
    `REQUIRED_HUMAN_INPUT`, so a caller can report "this record is publishable
    but incomplete, and here is exactly what a human still owes it" instead of
    publishing a record whose gaps only show up when someone reads it."""
    out: list = []
    for key in THIRD_PARTY_COMPONENT_FIELDS:
        value = payload.get(key)
        if value == REQUIRED_HUMAN_INPUT:
            out.append(key)
        elif isinstance(value, dict):
            out.extend(f"{key}.{k}" for k, v in sorted(value.items())
                       if v == REQUIRED_HUMAN_INPUT)
        elif isinstance(value, list) and REQUIRED_HUMAN_INPUT in value:
            out.append(key)
    return out


# ===========================================================================
# Rendering
# ===========================================================================

def render_checklist_table(audit: SyoscbSourceAudit) -> str:
    rows = [{"item": k, "status": v["status"], "count": v["count"],
             "evidence": "; ".join(str(e) for e in v["evidence"][:3]) or "(none)"}
            for k, v in audit_checklist(audit).items()]
    return render_markdown_table(
        [("item", "SYOSCB-1 ITEM"), ("status", "STATUS"), ("count", "COUNT"),
         ("evidence", "EVIDENCE (first 3)")], rows,
        empty_note="(no checklist produced -- this is a defect, not a finding)")


def render_class_table(audit: SyoscbSourceAudit) -> str:
    rows = [{"name": c["name"], "base": c["base_class"] or "(none)", "role": c["role"],
             "tier": c["tier"], "location": f"{c['file']}:{c['line']}"}
            for c in audit.classes]
    return render_markdown_table(
        [("name", "CLASS"), ("base", "EXTENDS"), ("role", "ROLE"),
         ("tier", "TIER"), ("location", "LOCATION")], rows,
        empty_note="(no classes found in this source tree)")


def render_compare_algorithm_table(audit: SyoscbSourceAudit) -> str:
    rows = []
    for ordering in ORDERING_VALUES:
        hit = audit.compare_algorithms.get(ordering)
        rows.append({"ordering": ordering,
                     "cls": hit["class"] if hit else REQUIRED_HUMAN_INPUT,
                     "location": f"{hit['file']}:{hit['line']}" if hit else "(none)"})
    return render_markdown_table(
        [("ordering", "SCOREBOARD PLAN `ordering`"), ("cls", "UPSTREAM CLASS"),
         ("location", "LOCATION")], rows)


def render_source_audit_report(audit: SyoscbSourceAudit,
                               payload: Optional[dict] = None) -> str:
    """The full SYOSCB-1 (+ optional SYOSCB-3) markdown report.

    Runs `assert_no_emittable_sv()` on its own output before returning, so the
    report cannot become a back door for pre-approval implementation."""
    unanswered = unanswered_audit_items(audit)
    parts = [
        "# SYOSCB-1 SOURCE AUDIT",
        "",
        f"- SOURCE_ROOT: `{audit.root}` (read-only; nothing copied into this repository)",
        f"- VERSION: `{audit.version}`"
        + (f" ({audit.version_evidence})" if audit.version_evidence else ""),
        f"- LICENSE: `{audit.license['spdx_id']}`"
        f" ({audit.license['license_file'] or 'no license file found'})",
        f"- COPYRIGHT: {audit.license['copyright']}"
        + (f" ({audit.license['copyright_evidence']})"
           if audit.license["copyright_evidence"] else ""),
        f"- FILES AUDITED: {len(audit.files)}",
        f"- AUDIT FINGERPRINT: `{audit_fingerprint(audit)}`",
        f"- UVM DEPENDENCY: requires_uvm={audit.uvm_dependency['requires_uvm']}, "
        f"version={audit.uvm_dependency['uvm_version']}",
        "",
        "## SYOSCB-1 CHECKLIST",
        "",
        render_checklist_table(audit),
        "",
        ("UNANSWERED ITEMS: " + ", ".join(unanswered)) if unanswered
        else "UNANSWERED ITEMS: (none -- all sixteen answered from the tree)",
        "",
        "## CLASS INVENTORY",
        "",
        render_class_table(audit),
        "",
        "## COMPARE ALGORITHM -> SCOREBOARD PLAN `ordering`",
        "",
        render_compare_algorithm_table(audit),
        "",
        "## COMPILE ORDER (package include sequence, source order)",
        "",
    ]
    order = audit.package.get("compile_order") or []
    parts.extend([f"{i}. `{inc}`" for i, inc in enumerate(order, start=1)]
                 or ["(no package file with includes found)"])
    parts += ["", "## KNOWN LIMITATIONS (upstream release notes)", ""]
    parts.extend([f"- {lim}" for lim in audit.known_limitations]
                 or ["- (none stated upstream)"])

    if payload is not None:
        blockers = registration_blockers(payload)
        parts += [
            "", "## SYOSCB-3 KNOWLEDGE CENTER REGISTRATION PAYLOAD", "",
            "Built, NOT published. Publishing is an explicit "
            "`KnowledgeCenterClient.record_component()` call on the existing shared store.",
            "",
        ]
        parts.extend(f"- `{k}`: {payload.get(k)!r}" for k in THIRD_PARTY_COMPONENT_FIELDS)
        parts += ["",
                  ("REGISTRATION BLOCKERS (fields a human still owes this record): "
                   + ", ".join(blockers)) if blockers
                  else "REGISTRATION BLOCKERS: (none)"]

    text = "\n".join(parts) + "\n"
    assert_no_emittable_sv(text, label="syoscb source audit report")
    return text


def _main(argv=None) -> int:  # pragma: no cover - thin CLI over tested functions
    import argparse
    import json

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.syoscb_source_audit",
        description="SYOSCB-1 read-only audit of an uvm_syoscb source tree, and the "
                    "SYOSCB-3 Knowledge Center registration payload built from it. "
                    "Reads only; never copies, never publishes.")
    ap.add_argument("root", help="upstream source directory to audit, read-only")
    ap.add_argument("--json", action="store_true", help="emit the audit as JSON")
    ap.add_argument("--registration-payload", action="store_true",
                    help="also build (never publish) the SYOSCB-3 registration payload")
    ap.add_argument("--l5-destination", default=None,
                    help="the approved in-repo destination, if a human has decided one")
    ap.add_argument("--assert-not-vendored", metavar="REPO_ROOT", default=None,
                    help="fail if any upstream file is already inside this repository")
    args = ap.parse_args(argv)

    audit = audit_syoscb_source(args.root)
    payload = (build_component_registration_payload(
        audit, l5_destination=args.l5_destination)
        if args.registration_payload else None)
    if args.assert_not_vendored:
        approval = load_vendoring_approval(args.assert_not_vendored)
        assert_not_vendored(args.assert_not_vendored, audit, approval=approval)
    if args.json:
        doc = audit.to_dict()
        if payload is not None:
            doc["registration_payload"] = payload
        print(json.dumps(doc, indent=2, sort_keys=True))
    else:
        print(render_source_audit_report(audit, payload))
    assert_source_unmodified(audit)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
