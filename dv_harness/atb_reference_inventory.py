"""dv_harness/atb_reference_inventory.py -- a real, READ-ONLY capability
inventory over the ATB (AutoTestBench, formerly named "L3", renamed this
session) reference tree.

WHAT THIS IS
------------
ATB is a real reference tree containing real `coretop/` and `soc/`
subdirectories, including a real vendored-looking SyoSil scoreboard source
under `soc/uvc/scb/`. This module inspects it, structurally and read-only,
and answers the question `syoscb_source_audit.py` already answers for the
UPSTREAM `uvm_syoscb` tree, but one level up: not "what does this one
third-party library contain", but "what capabilities does this whole
reference ENVIRONMENT contain, which of them are wired in, which are
present-but-unused, which drift from what this project already vendored,
and -- for any capability a caller actually needs -- can it be reused from
here, from an already-approved vendored copy, or must it be reported
BLOCKED because neither exists."

The root is ALWAYS a caller-supplied parameter (`discover_atb_capabilities(root, ...)`).
The real path this session's ATB happens to live at
(`D:/DV/Task/DV_Agent_Harness_L5/ATB`) is used only by this module's own
tests and by nothing hardcoded here -- a caller may point this at a
different reference tree later without touching this file.

WHAT THIS REUSES RATHER THAN REBUILDS
--------------------------------------
  * `vip_symbol_index.index_source_text()` is the ONLY class scanner used
    here, exactly as `syoscb_source_audit.py` already established: it
    retains DECLARATIONS AND LOCATIONS ONLY (class name, base class,
    file:line) and NEVER a method body. `assert_no_bodies_retained()` is
    run over the result, making that a checkable property rather than a
    promise.
  * `verible_parser.py` is the ONLY module-level (RTL-shaped) structural
    scanner used here, for the handful of ATB constructs
    `vip_symbol_index.py` was never built to see -- a bind CONNECTOR
    `module` and a testbench top `module`. It is used the same
    declaration-only way `env_manifest.py`/`phy_boundary.py` already use
    it: ports and instances, never a statement body. A machine with no
    real `verible-verilog-syntax` on PATH degrades this ONE layer to an
    honest `NOT_AVAILABLE` (never a silent zero read as "none exist") --
    class/interface discovery is unaffected either way.
  * `amba_scoreboard_env.InspectedFile` is the same read-only-proof record
    `syoscb_source_audit.py` reuses, so "which files did we read, and were
    they unchanged afterwards" has one shape in this repo rather than two.
  * `connectivity.render_markdown_table()` renders the one optional report
    table this module produces, when it is importable -- the repo's only
    parameterized table renderer, not a second hand-rolled one.

An `interface` declaration (ATB's bind interfaces under `uvc/bind/`) is the
one construct NEITHER existing tool indexes: `vip_symbol_index.py` only
matches `class`, and `verible_parser.extract_modules()` only extracts
`kModuleDeclaration`. `_index_interfaces()` below is a small, LOCAL,
declaration-line-only regex scan -- the same discipline as both of the
above (name + file:line, never a signal list, never a body) -- built only
because neither reused tool covers this one shape.

THE STATUS VOCABULARY (verbatim, per this module's own governing task)
------------------------------------------------------------------------
PROVEN / IMPLEMENTED_UNPROVEN / PARTIAL / PRESENT_UNUSED / DUPLICATE /
STALE / MISSING / BLOCKED / UNKNOWN. See `classify_capability_status()`'s
own docstring for what each one requires as real evidence, and the
precedence order when more than one condition applies to the same
capability. `PROVEN` requires a caller-declared, cited piece of real
regression/simulation evidence naming this exact capability -- this
module manufactures none on its own, since ATB is a read-only reference
tree with no evidence store of its own wired to it.

THE LITERAL REUSE-THEN-BLOCK RULE
----------------------------------
`resolve_capability_reuse()` is the rule as code: given one capability
name a caller needs, (1) if ATB itself already has it, prefer reusing
ATB's own copy; ELSE (2) if an already-vendored, human-APPROVED reference
copy exists elsewhere in this project (a real
`dv_harness/*vendoring_approval*.json`-shaped record, in the exact shape
`syoscb_source_audit.VENDORING_APPROVAL_FILENAME` already established --
this module never imports that file, per this batch's file-safety scope,
so it re-derives its own minimal, equally fail-closed reader of the same
shape), reuse THAT copy; ELSE (3) report BLOCKED, naming every location
that was actually checked and found not to have it. There is no fourth
branch that proceeds with nothing.

THE ATB-ITSELF VENDORING QUESTION
------------------------------------
Copying any part of ATB into this v50 tree is a Phase-2 vendoring decision
requiring the SAME explicit human approval this project already applies
to SyoSil (see `dv_harness/syoscb_vendoring_approval.json`).
`atb_vendoring_approval_status()` answers, honestly and from real files on
disk, whether such an approval record exists FOR ATB ITSELF (as opposed to
for some other component, like SyoSil, that happens to also live under
`dv_harness/`). As of this task it does not, and this module creates
none -- it only ever reads.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dv_harness import vip_symbol_index
from dv_harness.amba_scoreboard_env import InspectedFile

try:
    from dv_harness import verible_parser
except Exception:  # pragma: no cover - verible_parser itself always imports
    verible_parser = None

try:
    from dv_harness.connectivity import render_markdown_table
except Exception:  # pragma: no cover - connectivity.py always imports in this repo
    render_markdown_table = None


class AtbReferenceInventoryError(ValueError):
    """A root that does not exist, a file that changed underneath a
    read-only audit, or a vendoring-approval-shaped record on disk that is
    malformed. Malformed is never read as absent -- that would make the
    Phase-2 vendoring check MORE permissive on a parse failure than on a
    genuinely missing file, exactly the reasoning
    `syoscb_source_audit.SyoscbSourceAuditError` already applies to its own
    `load_vendoring_approval()`."""

    def __init__(self, code: str, detail: Optional[dict] = None):
        self.code = code
        self.detail = dict(detail or {})
        super().__init__(f"{code}: {self.detail}")


# ===========================================================================
# Status vocabulary (verbatim, per this module's own governing task)
# ===========================================================================

STATUS_PROVEN = "PROVEN"
STATUS_IMPLEMENTED_UNPROVEN = "IMPLEMENTED_UNPROVEN"
STATUS_PARTIAL = "PARTIAL"
STATUS_PRESENT_UNUSED = "PRESENT_UNUSED"
STATUS_DUPLICATE = "DUPLICATE"
STATUS_STALE = "STALE"
STATUS_MISSING = "MISSING"
STATUS_BLOCKED = "BLOCKED"
STATUS_UNKNOWN = "UNKNOWN"

CAPABILITY_STATUS_VALUES: tuple = (
    STATUS_PROVEN, STATUS_IMPLEMENTED_UNPROVEN, STATUS_PARTIAL, STATUS_PRESENT_UNUSED,
    STATUS_DUPLICATE, STATUS_STALE, STATUS_MISSING, STATUS_BLOCKED, STATUS_UNKNOWN,
)

# ===========================================================================
# Capability-kind vocabulary, derived from ATB's own real directory shape
# (coretop/uvc/{bind,cb,seq}, soc/uvc/{bind,cb,scb,seq}) plus the two
# module-shaped constructs verible finds (a bind connector module, a
# testbench/DUT-wrapper top module).
# ===========================================================================

KIND_SCOREBOARD_COMPONENT = "SCOREBOARD_COMPONENT"
KIND_BIND_INTERFACE = "BIND_INTERFACE"
KIND_MONITOR_CALLBACK = "MONITOR_CALLBACK"
KIND_SEQUENCE_COLLECTION = "SEQUENCE_COLLECTION"
KIND_ENV_OR_TEST_COMPONENT = "ENV_OR_TEST_COMPONENT"
KIND_DUT_WRAPPER_MODULE = "DUT_WRAPPER_MODULE"
KIND_TESTBENCH_TOP_MODULE = "TESTBENCH_TOP_MODULE"
KIND_CONNECTOR_MODULE = "CONNECTOR_MODULE"
KIND_OTHER_CLASS = "OTHER_CLASS"

CAPABILITY_KIND_VALUES: tuple = (
    KIND_SCOREBOARD_COMPONENT, KIND_BIND_INTERFACE, KIND_MONITOR_CALLBACK,
    KIND_SEQUENCE_COLLECTION, KIND_ENV_OR_TEST_COMPONENT, KIND_DUT_WRAPPER_MODULE,
    KIND_TESTBENCH_TOP_MODULE, KIND_CONNECTOR_MODULE, KIND_OTHER_CLASS,
)

#: Directory segment -> capability kind for a CLASS-shaped declaration.
#: Checked against the real (already-verified) ATB layout:
#: `coretop|soc/uvc/{bind -> interfaces (handled separately),
#: cb -> callbacks, scb -> scoreboard, seq -> sequences}`.
_CLASS_KIND_BY_DIR: tuple = (
    ("scb", KIND_SCOREBOARD_COMPONENT),
    ("cb", KIND_MONITOR_CALLBACK),
    ("seq", KIND_SEQUENCE_COLLECTION),
)

#: Reference/vendored-family recognition, by directory segment + class-name
#: prefix. Used only to decide which project vendoring-approval record (if
#: any) a discovered ATB capability should be compared against for drift
#: (STALE). Never used to decide anything about correctness or priority.
#: `component_hint` restricts a family's drift comparison to an approval
#: record whose OWN `component` field names that same upstream family
#: (case-insensitive substring) -- without it, a wholesale mirror of ATB
#: ITSELF (e.g. an `atb_vendoring_approval.json`-shaped record whose
#: `l5_destination` is a byte-identical copy of the whole ATB tree) would
#: trivially "match" every ATB capability against its own mirror and never
#: report drift against anything. Real evidence found this the hard way:
#: `reference/ATB` genuinely is such a mirror in this project.
KNOWN_VENDORED_FAMILIES: dict = {
    "SYOSIL_SCOREBOARD": {"dir_marker": "scb", "name_prefix": "cl_syoscb",
                          "component_hint": "syoscb"},
}

# ===========================================================================
# Reuse-then-block resolution vocabulary
# ===========================================================================

RESOLUTION_REUSE_LOCAL = "REUSE_LOCAL_ATB_CAPABILITY"
RESOLUTION_REUSE_VENDORED = "REUSE_VENDORED_REFERENCE_COPY"
RESOLUTION_BLOCKED = "BLOCKED_NOTHING_TO_REUSE"

RESOLUTION_VALUES: tuple = (RESOLUTION_REUSE_LOCAL, RESOLUTION_REUSE_VENDORED, RESOLUTION_BLOCKED)

#: The same on-disk shape `syoscb_source_audit.VENDORING_APPROVAL_FILENAME`
#: already established, generalized to "any file under `dv_harness/` whose
#: name says it is a vendoring approval record" rather than one hardcoded
#: filename -- so a future second vendored component (a second
#: `<component>_vendoring_approval.json`) is discovered the same way.
VENDORING_APPROVAL_GLOB = "*vendoring_approval*.json"

_SOURCE_SUFFIXES: tuple = (".sv", ".svh", ".svi", ".v", ".vh")
_MODULE_SCAN_SUFFIXES: tuple = (".sv", ".svi", ".v")

_INTERFACE_RE = re.compile(r"^\s*interface\s+(?P<name>[A-Za-z_]\w*)")


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except ValueError:  # pragma: no cover - a path outside root cannot occur here
        return str(path).replace("\\", "/")


#: Directory segments a capability's OWN kind-family lives under. Used to
#: scope "is this really wired into the environment" one level narrower
#: than "is this subsystem" -- a class in `scb/` extended by ANOTHER class
#: that also lives in `scb/` is real, but it only proves the scoreboard
#: family is internally self-consistent, not that anything OUTSIDE that
#: family (`soc_base_env.sv`, a virtual sequencer, a bench top file) ever
#: actually plugs it into the running environment. `bind/`/`cb/`/`seq/`
#: capabilities in this real ATB tree genuinely ARE referenced from
#: outside their own directory (a bench top `` `include ``, a virtual
#: sequencer, an env-level directed-sequence call); the vendored-looking
#: `scb/` scoreboard, checked the same way, genuinely is not -- and that
#: distinction is exactly what PRESENT_UNUSED vs IMPLEMENTED_UNPROVEN
#: exists to surface.
_KIND_DIR_SEGMENTS: frozenset = frozenset({"scb", "cb", "seq", "bind"})


def _kind_dir_of(rel_path: str) -> Optional[str]:
    parts = rel_path.split("/")
    for seg in parts[:-1]:
        if seg in _KIND_DIR_SEGMENTS:
            return seg
    return None


def _subsystem_of(rel_path: str) -> str:
    """The top-level segment of a relative path (`"coretop"`, `"soc"`), or
    `""` for a path with no segment above it. Used to scope duplicate
    detection and family-completeness checks to ONE reference environment
    at a time -- `coretop` and `soc` each legitimately carry their own copy
    of, e.g., `user_svt_apb_master_bind_if.svi`, and that cross-environment
    duplication is by design, not a defect this module should flag."""
    parts = rel_path.split("/")
    return parts[0] if parts else ""


def _index_interfaces(text: str, file_label: str) -> list:
    """Every top-level `interface <name>` DECLARATION line in `text`, with
    its file:line -- name and location only, mirroring
    `vip_symbol_index.index_source_text()`'s own discipline for `class`.
    Never a signal, a parameter, or a body line."""
    out = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        m = _INTERFACE_RE.match(raw)
        if m:
            out.append({"name": m.group("name"), "file": file_label, "line": lineno})
    return out


def _classify_class_kind(rel_path: str, name: str) -> str:
    parts = rel_path.split("/")
    for seg, kind in _CLASS_KIND_BY_DIR:
        if seg in parts:
            return kind
    lowered = name.lower()
    if any(t in lowered for t in ("_env", "_test", "_configuration", "_virtual_sequencer")):
        return KIND_ENV_OR_TEST_COMPONENT
    if any(t in lowered for t in ("_sequence", "_sequencer")):
        return KIND_SEQUENCE_COLLECTION
    return KIND_OTHER_CLASS


def _classify_module_kind(rel_path: str, name: str) -> str:
    parts = [p.lower() for p in rel_path.split("/")]
    lowered_name = (name or "").lower()
    if "dut_wrapper" in parts or lowered_name.endswith("_dut_wrapper"):
        return KIND_DUT_WRAPPER_MODULE
    if "connector" in lowered_name:
        return KIND_CONNECTOR_MODULE
    if lowered_name.startswith("uvm_") and lowered_name.endswith("_tb"):
        return KIND_TESTBENCH_TOP_MODULE
    return KIND_OTHER_CLASS


# ===========================================================================
# Read-only-proof record + the manifest itself
# ===========================================================================

@dataclass
class AtbCapability:
    """One discovered capability -- a class, an interface, or a module --
    inside the ATB reference tree, structurally located and classified.
    Never carries a method body or a signal list; only a name, a kind, a
    location, and the honest status this module derived for it."""
    name: str
    kind: str
    file: str
    line: int
    base_class: Optional[str]
    subsystem: str
    referenced_elsewhere: bool
    status: str
    status_evidence: str
    tool: str  # "vip_symbol_index" | "verible_parser" | "interface_scan"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "file": self.file, "line": self.line,
            "base_class": self.base_class, "subsystem": self.subsystem,
            "referenced_elsewhere": self.referenced_elsewhere, "status": self.status,
            "status_evidence": self.status_evidence, "tool": self.tool,
        }


@dataclass
class AtbInventoryManifest:
    """ATB-1's complete read-only result for one reference tree."""
    root: str
    files: list                # list[InspectedFile]: EVERY file under root
    capabilities: list          # list[AtbCapability]
    module_discovery_status: str  # "AVAILABLE" | "NOT_AVAILABLE"
    module_discovery_reason: str

    def capabilities_with_status(self, status: str) -> list:
        return [c for c in self.capabilities if c.status == status]

    def capability_named(self, name: str) -> list:
        return [c for c in self.capabilities if c.name == name]

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "file_count": len(self.files),
            "inspected_files": [f.to_dict() for f in self.files],
            "capabilities": [c.to_dict() for c in self.capabilities],
            "module_discovery_status": self.module_discovery_status,
            "module_discovery_reason": self.module_discovery_reason,
            "status_counts": {
                s: len(self.capabilities_with_status(s)) for s in CAPABILITY_STATUS_VALUES
            },
        }


def assert_source_unmodified(manifest: AtbInventoryManifest) -> None:
    """"Inspect, do not modify" as a checkable property, the same
    reasoning `syoscb_source_audit.assert_source_unmodified()` applies to
    its own upstream tree. Re-reads every audited file and compares its
    sha256 against the digest recorded at audit time."""
    for item in manifest.files:
        path = Path(item.path)
        if not path.exists():
            raise AtbReferenceInventoryError("ATB_SOURCE_DISAPPEARED_DURING_AUDIT", {
                "path": item.path,
                "hint": "this audit is read-only; a file audited at the start must "
                        "still be there at the end"})
        if _sha256_bytes(path.read_bytes()) != item.sha256:
            raise AtbReferenceInventoryError("ATB_SOURCE_MODIFIED_DURING_AUDIT", {
                "path": item.path, "sha256_at_audit": item.sha256,
                "hint": "the ATB reference tree must never be written to by this module"})


def discover_atb_capabilities(root, *, verible_bin: Optional[str] = None,
                               use_verible: bool = True) -> AtbInventoryManifest:
    """The read-only structural scan of the real ATB tree at `root`.

    `root` is always a caller-supplied parameter -- never hardcoded here --
    so a caller may point this at a different reference tree later. A root
    that does not exist RAISES rather than returning an empty manifest: a
    mistyped path must never be indistinguishable from a reference tree
    with nothing in it."""
    base = Path(root)
    if not base.is_dir():
        raise AtbReferenceInventoryError("ATB_ROOT_NOT_FOUND", {
            "root": str(root),
            "hint": "ATB-1 audits the real reference tree read-only; a missing root "
                    "is an operator error, never an empty tree"})

    inspected: list = []
    texts: dict = {}
    for path in sorted(base.rglob("*"), key=lambda p: str(p).replace("\\", "/")):
        if not path.is_file():
            continue
        blob = path.read_bytes()
        rel = _rel(path, base)
        inspected.append(InspectedFile(path=str(path).replace("\\", "/"),
                                       sha256=_sha256_bytes(blob), bytes=len(blob)))
        if rel.lower().endswith(_SOURCE_SUFFIXES):
            texts[rel] = blob.decode("utf-8", errors="replace")

    # --- classes, via vip_symbol_index (declarations + locations only) ----
    classes: list = []
    for rel, text in texts.items():
        classes.extend(vip_symbol_index.index_source_text(text, rel))
    classes.sort(key=lambda c: (c["file"], c["line"]))
    vip_symbol_index.assert_no_bodies_retained({"classes": classes})

    # --- interfaces, via the one local declaration-only scan --------------
    interfaces: list = []
    for rel, text in texts.items():
        interfaces.extend(_index_interfaces(text, rel))

    # --- modules, via verible_parser (best-effort, degrades honestly) -----
    modules: list = []
    module_discovery_status = "NOT_AVAILABLE"
    module_discovery_reason = "verible_parser module is not importable in this environment"
    if use_verible and verible_parser is not None:
        real_bin = verible_bin or verible_parser.DEFAULT_VERIBLE_BIN
        version = verible_parser.get_verible_version(real_bin)
        if not version:
            module_discovery_reason = (
                f"{real_bin!r} not found on PATH; module-level (interface-connector / "
                "DUT-wrapper / testbench-top) capability discovery skipped -- class and "
                "interface discovery are unaffected")
        else:
            module_discovery_status = "AVAILABLE"
            module_discovery_reason = ""
            for rel in sorted(texts):
                if not rel.lower().endswith(_MODULE_SCAN_SUFFIXES):
                    continue
                try:
                    result = verible_parser.parse_file(base / rel, verible_bin=real_bin)
                except Exception:
                    # A file this scan cannot parse (an unresolved macro-only
                    # `.svi`, a genuine syntax variant) contributes no modules
                    # -- never a guess, and never a reason to fail the rest.
                    continue
                for m in result.modules:
                    if not m.name:
                        continue
                    modules.append({"name": m.name, "file": rel})

    # --- name -> subsystem-scoped declaration groups, for duplicate detect -
    class_locs: dict = {}
    for c in classes:
        subsystem = _subsystem_of(c["file"])
        class_locs.setdefault((subsystem, c["name"]), []).append(c)
    iface_locs: dict = {}
    for i in interfaces:
        subsystem = _subsystem_of(i["file"])
        iface_locs.setdefault((subsystem, i["name"]), []).append(i)

    all_names_by_subsystem: dict = {}
    for c in classes:
        all_names_by_subsystem.setdefault(_subsystem_of(c["file"]), set()).add(c["name"])
    for i in interfaces:
        all_names_by_subsystem.setdefault(_subsystem_of(i["file"]), set()).add(i["name"])

    def _referenced_elsewhere(name: str, own_file: str, subsystem: str) -> bool:
        """Whether some file OUTSIDE `name`'s own kind-directory (`scb/`,
        `cb/`, `seq/`, `bind/` -- or, for a capability with no such
        directory, any other file at all) in the SAME subsystem mentions
        `name` as a whole word -- an `extends`, an instantiation, a
        task/method call -- OR literally names the DECLARING FILE (its own
        basename, extension included). The second half exists because a
        real ATB bind interface (and, in general, any `` `include ``d
        header) is wired in by its FILENAME, not by the interface's own
        symbol name -- `soc/bench/uvm_soc_tb.sv` really does
        `` `include "user_svt_apb_master_bind_if.svi" ``, which never
        contains the bare word `svt_apb_master_bind_if` as its own
        whole-word token. Scoped to the subsystem (not the whole tree) so
        an intentional, separate coretop-vs-soc copy of the same file
        never makes the OTHER copy look "used". Scoped OUTSIDE the
        kind-directory so a class extended only by its own sibling in the
        same family reads as internally self-consistent, never as "wired
        into the environment" on that evidence alone -- the difference
        this module's own `scb/` finding turns on."""
        pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        own_basename = Path(own_file).name
        own_kind_dir = _kind_dir_of(own_file)
        for rel, text in texts.items():
            if rel == own_file or _subsystem_of(rel) != subsystem:
                continue
            if own_kind_dir is not None and _kind_dir_of(rel) == own_kind_dir:
                continue
            if pattern.search(text) or own_basename in text:
                return True
        return False

    #: Every module name verible found, regardless of subsystem -- used
    #: the same way `all_names_by_subsystem` is, so the cross-tool
    #: ambiguity check runs symmetrically: a class/interface colliding
    #: with a module name is UNKNOWN exactly as a module colliding with a
    #: class/interface name is.
    module_names: set = {m["name"] for m in modules}

    def _ambiguity_evidence(name: str, file: str, other_tool: str) -> str:
        return (f"{file}: a {other_tool} declaration named {name!r} was also found "
                "elsewhere in this tree, structurally shaped as something else -- "
                "ambiguous across two independent structural scans, not resolved "
                "by this module")

    capabilities: list = []
    for c in classes:
        subsystem = _subsystem_of(c["file"])
        kind = _classify_class_kind(c["file"], c["name"])
        siblings = class_locs.get((subsystem, c["name"]), [])
        referenced = _referenced_elsewhere(c["name"], c["file"], subsystem)
        if c["name"] in module_names:
            status = STATUS_UNKNOWN
            evidence = _ambiguity_evidence(c["name"], c["file"], "module")
        else:
            status, evidence = _derive_status(
                name=c["name"], kind=kind, file=c["file"], subsystem=subsystem,
                siblings=siblings, referenced_elsewhere=referenced)
        capabilities.append(AtbCapability(
            name=c["name"], kind=kind, file=c["file"], line=c["line"],
            base_class=c.get("base_class"), subsystem=subsystem,
            referenced_elsewhere=referenced, status=status, status_evidence=evidence,
            tool="vip_symbol_index"))

    for i in interfaces:
        subsystem = _subsystem_of(i["file"])
        siblings = iface_locs.get((subsystem, i["name"]), [])
        referenced = _referenced_elsewhere(i["name"], i["file"], subsystem)
        if i["name"] in module_names:
            status = STATUS_UNKNOWN
            evidence = _ambiguity_evidence(i["name"], i["file"], "module")
        else:
            status, evidence = _derive_status(
                name=i["name"], kind=KIND_BIND_INTERFACE, file=i["file"], subsystem=subsystem,
                siblings=siblings, referenced_elsewhere=referenced)
        capabilities.append(AtbCapability(
            name=i["name"], kind=KIND_BIND_INTERFACE, file=i["file"], line=i["line"],
            base_class=None, subsystem=subsystem, referenced_elsewhere=referenced,
            status=status, status_evidence=evidence, tool="interface_scan"))

    for m in modules:
        subsystem = _subsystem_of(m["file"])
        kind = _classify_module_kind(m["file"], m["name"])
        referenced = _referenced_elsewhere(m["name"], m["file"], subsystem)
        # Cross-tool ambiguity: a name verible reports as a MODULE that
        # vip_symbol_index/`_index_interfaces` ALSO reports as a class or
        # interface name (in this or any subsystem) is genuinely UNKNOWN --
        # two independent structural scans disagreeing about what this name
        # represents, never resolved by picking one.
        if any(m["name"] == n for names in all_names_by_subsystem.values() for n in names):
            status = STATUS_UNKNOWN
            evidence = _ambiguity_evidence(m["name"], m["file"], "class/interface")
        else:
            status, evidence = _derive_status(
                name=m["name"], kind=kind, file=m["file"], subsystem=subsystem,
                siblings=[], referenced_elsewhere=referenced)
        capabilities.append(AtbCapability(
            name=m["name"], kind=kind, file=m["file"], line=0, base_class=None,
            subsystem=subsystem, referenced_elsewhere=referenced,
            status=status, status_evidence=evidence, tool="verible_parser"))

    capabilities.sort(key=lambda cap: (cap.subsystem, cap.file, cap.line, cap.name))

    return AtbInventoryManifest(
        root=str(base).replace("\\", "/"), files=inspected, capabilities=capabilities,
        module_discovery_status=module_discovery_status,
        module_discovery_reason=module_discovery_reason)


def _derive_status(*, name: str, kind: str, file: str, subsystem: str,
                    siblings: list, referenced_elsewhere: bool) -> tuple:
    """One capability's status, worst-first, per this module's own
    precedence: a real DUPLICATE (name collision within one subsystem) is
    reported ahead of everything else, because a human has to resolve
    which declaration is real before "is it wired in" is even a coherent
    question to ask about it. PROVEN is never derived HERE -- it requires
    caller-declared evidence and is only ever applied afterward, by
    `apply_proof_evidence()`, over a capability this function already
    classified."""
    if len(siblings) > 1:
        locations = "; ".join(f"{s['file']}:{s['line']}" for s in siblings)
        return (STATUS_DUPLICATE,
                f"{name!r} is declared more than once within the {subsystem or '(root)'} "
                f"subsystem: {locations}")
    if referenced_elsewhere:
        return (STATUS_IMPLEMENTED_UNPROVEN,
                f"{file}: {name!r} is referenced from another file in the "
                f"{subsystem or '(root)'} subsystem, but no real regression/simulation "
                "evidence for it was supplied to this audit")
    return (STATUS_PRESENT_UNUSED,
            f"{file}: {name!r} is declared but not referenced by any other file in the "
            f"{subsystem or '(root)'} subsystem")


def apply_proof_evidence(manifest: AtbInventoryManifest, proof_evidence: dict) -> AtbInventoryManifest:
    """Promotes a capability to PROVEN -- and ONLY this function may -- when
    a caller supplies a real, non-empty evidence citation naming it.
    `proof_evidence` is `{capability_name: "citation text"}`; a blank or
    missing citation is refused rather than silently accepted, since an
    unearned PROVEN is the single most expensive status this vocabulary can
    assign. Never mutates `manifest`'s own capability list in place --
    returns a new manifest whose OTHER fields are unchanged."""
    if not proof_evidence:
        return manifest
    promoted = []
    for cap in manifest.capabilities:
        citation = (proof_evidence.get(cap.name) or "").strip()
        if citation and cap.status != STATUS_DUPLICATE:
            promoted.append(AtbCapability(
                name=cap.name, kind=cap.kind, file=cap.file, line=cap.line,
                base_class=cap.base_class, subsystem=cap.subsystem,
                referenced_elsewhere=cap.referenced_elsewhere, status=STATUS_PROVEN,
                status_evidence=f"caller-declared evidence: {citation}", tool=cap.tool))
        else:
            promoted.append(cap)
    return AtbInventoryManifest(
        root=manifest.root, files=manifest.files, capabilities=promoted,
        module_discovery_status=manifest.module_discovery_status,
        module_discovery_reason=manifest.module_discovery_reason)


# ===========================================================================
# Expected-capability completeness (PARTIAL / MISSING), against a
# caller-DECLARED expectation list -- never a hardcoded universal one, the
# same reason `config_variant_coverage.py`'s dimensions are caller-declared
# rather than guessed.
# ===========================================================================

@dataclass
class MissingCapability:
    name: str
    reason: str

    def to_dict(self) -> dict:
        return {"name": self.name, "reason": self.reason}


def evaluate_expected_capabilities(manifest: AtbInventoryManifest,
                                    expected_names: list) -> dict:
    """Given a caller-declared list of capability names the caller expects
    ATB to provide (a "family" the caller needs completely), reports which
    are present anywhere in the manifest and which are genuinely absent.

    Returns `{"present": [...], "missing": [MissingCapability, ...],
    "family_status": "COMPLETE" | "PARTIAL" | "MISSING"}` --
    COMPLETE only when every declared name resolves to at least one real
    capability; MISSING only when NONE do; PARTIAL otherwise. An empty
    `expected_names` is refused rather than silently reporting COMPLETE
    over nothing."""
    if not expected_names:
        raise AtbReferenceInventoryError("NO_EXPECTED_CAPABILITIES_DECLARED", {
            "hint": "a completeness check needs a real, caller-declared expectation "
                    "list; this module invents no universal one"})
    known = {cap.name for cap in manifest.capabilities}
    present = [n for n in expected_names if n in known]
    missing = [MissingCapability(name=n, reason=(
        f"{n!r} was not discovered anywhere under {manifest.root} -- checked every "
        "class, interface and module this audit found"))
        for n in expected_names if n not in known]
    if not missing:
        family_status = "COMPLETE"
    elif not present:
        family_status = "MISSING"
    else:
        family_status = STATUS_PARTIAL
    return {"present": present, "missing": missing, "family_status": family_status}


# ===========================================================================
# STALE detection: content drift against this project's own already-approved
# vendored reference copy of a known family.
# ===========================================================================

def find_vendored_family_match(capability: AtbCapability, approval_records: list,
                                project_root) -> Optional[dict]:
    """Whether `capability` belongs to a KNOWN_VENDORED_FAMILIES family, and
    if so, whether one of `approval_records`' own `l5_destination` trees
    contains a same-basename file this project already vendored. Returns
    `None` when the capability matches no known family, or no approval's
    destination contains a same-named file -- never a guess."""
    for _family, spec in KNOWN_VENDORED_FAMILIES.items():
        if spec["dir_marker"] not in capability.file.split("/"):
            continue
        if not capability.name.startswith(spec["name_prefix"]):
            continue
        hint = spec.get("component_hint")
        basename = Path(capability.file).name
        for record in approval_records:
            if hint and hint.lower() not in (record.get("component") or "").lower():
                continue
            dest = Path(project_root) / record.get("l5_destination", "")
            if not dest.is_dir():
                continue
            for candidate in dest.rglob(basename):
                if candidate.is_file():
                    return {"approval_file": record["_approval_file"],
                            "l5_destination": record.get("l5_destination"),
                            "vendored_file": _rel(candidate, Path(project_root))}
    return None


def evaluate_drift_against_vendored(manifest: AtbInventoryManifest, approval_records: list,
                                     project_root) -> list:
    """For every capability in `manifest` that belongs to a known vendored
    family AND matches an already-approved vendored copy on real content,
    reports whether the two DIFFER (STALE) or agree. Never claims which
    side is "newer" -- only that they diverge, citing both real files and
    their real sha256 digests, and that a human must resolve which is
    authoritative. Returns a list of `{capability, status, evidence}`
    dicts; a capability with no vendored match at all is not returned."""
    base = Path(manifest.root)
    out = []
    for cap in manifest.capabilities:
        match = find_vendored_family_match(cap, approval_records, project_root)
        if match is None:
            continue
        atb_path = base / cap.file
        vendored_path = Path(project_root) / match["vendored_file"]
        atb_hash = _sha256_bytes(atb_path.read_bytes())
        vendored_hash = _sha256_bytes(vendored_path.read_bytes())
        if atb_hash == vendored_hash:
            out.append({"capability": cap.name, "status": "MATCHES_VENDORED_COPY",
                        "evidence": f"{cap.file} is byte-identical to the vendored "
                                    f"{match['vendored_file']} (approved by "
                                    f"{match['approval_file']})"})
        else:
            out.append({"capability": cap.name, "status": STATUS_STALE,
                        "evidence": (
                            f"{cap.file} (sha256 {atb_hash[:12]}...) differs from this "
                            f"project's own already-vendored {match['vendored_file']} "
                            f"(sha256 {vendored_hash[:12]}...), approved by "
                            f"{match['approval_file']} -- which side is stale relative to "
                            "the other is NOT determined by this module; a human must "
                            "resolve it")})
    return out


# ===========================================================================
# Project-side vendoring-approval records: reading (never creating) the
# same shape `syoscb_source_audit.VENDORING_APPROVAL_FILENAME` already
# established, generalized to every such file under `dv_harness/` rather
# than one hardcoded name. Re-derived locally rather than imported, because
# `syoscb_source_audit.py` is on this batch's claimed-file list.
# ===========================================================================

def find_project_vendoring_approval_records(project_root) -> list:
    """Every real `dv_harness/*vendoring_approval*.json` file under
    `project_root`, parsed. A file that is not valid JSON, or that is valid
    JSON but is not an object carrying at least `approved` and
    `l5_destination`, RAISES rather than being silently skipped -- the same
    fail-closed reasoning `syoscb_source_audit.load_vendoring_approval()`
    already applies to its own one file, generalized here to a directory of
    them. Returns `[]` (never raises) when no such file exists at all."""
    root = Path(project_root)
    dv_harness_dir = root / "dv_harness"
    out = []
    if not dv_harness_dir.is_dir():
        return out
    for path in sorted(dv_harness_dir.glob(VENDORING_APPROVAL_GLOB)):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AtbReferenceInventoryError("VENDORING_APPROVAL_UNREADABLE", {
                "path": str(path), "error": str(exc)}) from exc
        if not isinstance(record, dict) or "approved" not in record or "l5_destination" not in record:
            raise AtbReferenceInventoryError("VENDORING_APPROVAL_MALFORMED", {
                "path": str(path),
                "hint": "an approval record must be a JSON object carrying at least "
                        "'approved' and 'l5_destination'"})
        record = dict(record)
        record["_approval_file"] = str(path).replace("\\", "/")
        out.append(record)
    return out


def atb_vendoring_approval_status(project_root, atb_root) -> dict:
    """Whether a real, on-disk approval record exists authorizing vendoring
    ATB ITSELF (as opposed to some other component that happens to share
    the same `dv_harness/*vendoring_approval*.json` shape) into this
    project. Matches only on an EXACT resolved-path identity between a
    record's own `source_reference` and `atb_root` -- no fuzzy name
    matching, since a wrong match here would misreport whether a real human
    decision exists. Never writes anything; this module creates no
    approval record."""
    records = find_project_vendoring_approval_records(project_root)
    atb_resolved = str(Path(atb_root).resolve()).replace("\\", "/")
    for record in records:
        source_reference = record.get("source_reference") or ""
        try:
            candidate_resolved = str(Path(source_reference).resolve()).replace("\\", "/")
        except OSError:  # pragma: no cover - a malformed path string
            candidate_resolved = source_reference
        if candidate_resolved.lower() == atb_resolved.lower() and record.get("approved"):
            return {"approved": True, "record": record, "reason": (
                f"{record['_approval_file']} approves vendoring {source_reference} "
                f"(ATB) into {record.get('l5_destination')}")}
    return {"approved": False, "record": None, "reason": (
        f"no vendoring-approval record under {project_root} names {atb_root} as its "
        f"source_reference; {len(records)} other approval record(s) found on disk "
        f"cover a different source_reference each"
        if records else
        f"no vendoring-approval record exists anywhere under {project_root}")}


# ===========================================================================
# The literal reuse-then-block rule
# ===========================================================================

def resolve_capability_reuse(capability_name: str, manifest: AtbInventoryManifest,
                              approval_records: list, project_root, *,
                              vendored_suffixes: tuple = _SOURCE_SUFFIXES) -> dict:
    """The reuse-then-block rule for one named capability need:

    1. If `manifest` already contains a capability with this exact name,
       prefer reusing IT -- `RESOLUTION_REUSE_LOCAL`, citing ATB's own
       file:line and its currently-derived status.
    2. Else, if any of `approval_records`' own `l5_destination` trees
       (already human-approved to exist inside this project) contains a
       real class/interface declaration of this name, reuse THAT --
       `RESOLUTION_REUSE_VENDORED`, citing the approving record and the
       real vendored file:line.
    3. Else, `RESOLUTION_BLOCKED`, naming every location this function
       actually checked and found nothing at -- never silently proceeding
       with nothing."""
    local_hits = manifest.capability_named(capability_name)
    if local_hits:
        hit = local_hits[0]
        return {
            "resolution": RESOLUTION_REUSE_LOCAL, "capability_name": capability_name,
            "citation": f"{hit.file}:{hit.line}", "capability_status": hit.status,
            "reason": f"{capability_name!r} already exists in ATB at {hit.file}:{hit.line} "
                      f"(status {hit.status})",
        }

    checked_destinations = []
    for record in approval_records:
        if not record.get("approved"):
            continue
        dest = Path(project_root) / record.get("l5_destination", "")
        checked_destinations.append(str(dest).replace("\\", "/"))
        if not dest.is_dir():
            continue
        for candidate in sorted(dest.rglob("*")):
            if not candidate.is_file() or candidate.suffix.lower() not in vendored_suffixes:
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace")
            hits = vip_symbol_index.index_source_text(text, str(candidate))
            hits += [{"name": h["name"], "file": str(candidate), "line": h["line"]}
                     for h in _index_interfaces(text, str(candidate))]
            for h in hits:
                if h["name"] == capability_name:
                    return {
                        "resolution": RESOLUTION_REUSE_VENDORED, "capability_name": capability_name,
                        "citation": f"{_rel(candidate, Path(project_root))}:{h['line']}",
                        "approval_file": record["_approval_file"],
                        "reason": (
                            f"{capability_name!r} is not in ATB, but a real, approved "
                            f"vendored copy exists at {_rel(candidate, Path(project_root))}:"
                            f"{h['line']} per {record['_approval_file']}"),
                    }

    return {
        "resolution": RESOLUTION_BLOCKED, "capability_name": capability_name,
        "checked_locations": [manifest.root] + checked_destinations,
        "reason": (
            f"{capability_name!r} was not found in ATB ({manifest.root}) and no "
            f"already-approved vendored copy ({', '.join(checked_destinations) or '(none approved)'}) "
            "contains it either -- nothing to reuse"),
    }


# ===========================================================================
# Rendering
# ===========================================================================

def render_capability_table(manifest: AtbInventoryManifest) -> str:
    if render_markdown_table is None:  # pragma: no cover - connectivity.py always imports
        return "(connectivity.render_markdown_table is not importable in this environment)"
    rows = [{"name": c.name, "kind": c.kind, "subsystem": c.subsystem or "(root)",
             "status": c.status, "location": f"{c.file}:{c.line}"}
            for c in manifest.capabilities]
    return render_markdown_table(
        [("name", "CAPABILITY"), ("kind", "KIND"), ("subsystem", "SUBSYSTEM"),
         ("status", "STATUS"), ("location", "LOCATION")], rows,
        empty_note="(no capabilities discovered in this tree)")


def render_inventory_report(manifest: AtbInventoryManifest, *,
                             vendoring_status: Optional[dict] = None) -> str:
    counts = {s: len(manifest.capabilities_with_status(s)) for s in CAPABILITY_STATUS_VALUES}
    parts = [
        "# ATB REFERENCE INVENTORY",
        "",
        f"- ROOT: `{manifest.root}` (read-only; nothing copied into this repository)",
        f"- FILES AUDITED: {len(manifest.files)}",
        f"- CAPABILITIES DISCOVERED: {len(manifest.capabilities)}",
        f"- MODULE DISCOVERY (verible): {manifest.module_discovery_status}"
        + (f" -- {manifest.module_discovery_reason}" if manifest.module_discovery_reason else ""),
        "",
        "## STATUS COUNTS",
        "",
    ]
    parts.extend(f"- {s}: {counts[s]}" for s in CAPABILITY_STATUS_VALUES)
    parts += ["", "## CAPABILITY INVENTORY", "", render_capability_table(manifest)]
    if vendoring_status is not None:
        parts += [
            "", "## ATB-ITSELF VENDORING APPROVAL (SYOSCB-2/33-style Phase-2 gate)", "",
            f"- APPROVED: {vendoring_status['approved']}",
            f"- {vendoring_status['reason']}",
        ]
    return "\n".join(parts) + "\n"
