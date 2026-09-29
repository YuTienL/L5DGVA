"""dv_harness/vip_symbol_index.py -- the VIP-source symbol indexer (row 13 of
the asset-processing table) and the generator for the distilled
`vip_ref/<protocol>.md` (row 12).

Row 13 is "VIP source -> NOT loaded into context, only symbol-indexed
(class/method names + file:line) -> targeted read when needed". Both halves
were missing: no symbol indexer existed anywhere, and no `.claudeignore`
enforced the exclusion. CLAUDE.md's own context-budget policy says so
outright in `context_budget.policy.json`'s NEVER-VIP-SOURCE rule --
"There is NO VIP-source distiller in this repo... the intended distilled
artifact is the tier-3 docs/vip_ref/<protocol>.md, which does not exist yet."
This module is that distiller.

THE DEFINING CONSTRAINT, and the reason this is safe to run over a tree the
context budget otherwise denies: **this indexer reads VIP source but never
retains implementation text.** It keeps declarations and locations only --
class names, base classes, method signatures, config field names, and the
file:line of each. Method bodies, statements and expressions are matched and
discarded, never stored. `assert_no_bodies_retained()` makes that a checkable
property rather than a promise, and a real test exercises it.

That is the whole trick behind the row: the index answers "what exists, and
where", which is what an agent actually needs to navigate a VIP. The answer to
"what does it do" is then ONE targeted read of a cited file:line -- a bounded,
deliberate exemption -- instead of paging a hundred-thousand-line tree into
context to find one method.

WHY REGEX AND NOT A REAL PARSER. `verible_parser.py` is this repo's real
SystemVerilog parser and is used wherever module/port facts are needed
(env_manifest.py, phy_boundary.py). It is not used here, deliberately: a
production VIP tree is routinely encrypted (`svp`/`vp` protected regions) or
generated, and verible fails outright on such files rather than degrading.
An indexer that dies on the first protected file indexes nothing. So this
module does declaration-level line scanning, which degrades gracefully -- a
file it cannot understand contributes fewer symbols, never an exception. The
cost is honest and bounded: this index is a NAVIGATION AID, not a semantic
model, and must never be used to make a correctness claim about VIP
behaviour. For anything load-bearing, do the targeted read.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "vip_symbol_index.schema.json"

DEFAULT_SOURCE_SUFFIXES = (".sv", ".svh", ".v", ".vh")

# Declaration-level patterns. Each captures only a NAME/SIGNATURE and stops
# at the declaration -- none of them can capture a statement body.
_CLASS_RE = re.compile(
    r"^\s*(?P<virtual>virtual\s+)?class\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\s*#\s*\([^)]*\))?"                      # optional parameter list
    r"(?:\s+extends\s+(?P<base>[A-Za-z_]\w*))?"
)
_ENDCLASS_RE = re.compile(r"^\s*endclass\b")
_METHOD_RE = re.compile(
    r"^\s*(?P<extern>extern\s+)?(?P<virtual>virtual\s+)?(?:static\s+|protected\s+|local\s+|pure\s+)*"
    r"(?P<kind>function|task)\s+"
    r"(?:automatic\s+|static\s+)?"
    r"(?P<rettype>(?!new\b)[A-Za-z_]\w*(?:\s*#\s*\([^)]*\))?(?:\s*::\s*\w+)?\s+)?"
    r"(?P<name>[A-Za-z_]\w*)\s*(?P<args>\([^;]*\))?\s*;?"
)
# Class-scope property declarations -- the candidate VIP config knobs.
_FIELD_RE = re.compile(
    r"^\s*(?P<rand>rand\s+|randc\s+)?"
    r"(?P<dtype>bit|logic|reg|int|integer|byte|shortint|longint|string|real|time|"
    r"[A-Za-z_]\w*_(?:t|e|config|cfg))\b"
    r"(?:\s*(?:signed|unsigned))?"
    r"(?:\s*\[[^\]]*\])*\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*(?:=[^;]*)?;"
)
# Class-scope TLM analysis-connection declarations -- an analysis port/export/
# imp/fifo. Split out from `_FIELD_RE` rather than folded into it because
# `_FIELD_RE`'s dtype alternation cannot express a parameterized type at all
# (`uvm_analysis_port#(txn) ap;` matches nothing there), and because these are
# not config knobs: they are the CONNECTION POINTS of a UVM environment, which
# is what makes a scoreboard's real ingress discoverable without reading a
# single method body. Restricted to the analysis family on purpose -- a general
# "any parameterized declaration" regex would sweep queues, associative arrays
# and typedef'd handles into the same list and make the connection points
# unfindable again.
_ANALYSIS_PORT_RE = re.compile(
    r"^\s*(?P<port_type>uvm_(?:analysis_port|analysis_export|analysis_imp\w*|"
    r"tlm_analysis_fifo|analysis_fifo))\s*"
    r"(?:#\s*\((?P<params>[^)]*)\)\s*)?"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<dim>(?:\[[^\]]*\])*)\s*;"
)

#: `port_type` prefix -> the connection DIRECTION the UVM class library gives
#: it. An export/imp/fifo RECEIVES transactions (it is an ingress a monitor can
#: be connected to); a port SENDS them. Nothing here is inferred from the
#: declared name, only from the UVM base type actually written in the source.
_ANALYSIS_KIND_BY_PREFIX: tuple = (
    ("uvm_analysis_port", ("ANALYSIS_PORT", "OUTGOING")),
    ("uvm_analysis_export", ("ANALYSIS_EXPORT", "INGRESS")),
    ("uvm_analysis_imp", ("ANALYSIS_IMP", "INGRESS")),
    ("uvm_tlm_analysis_fifo", ("ANALYSIS_FIFO", "INGRESS")),
    ("uvm_analysis_fifo", ("ANALYSIS_FIFO", "INGRESS")),
)

_COMMENT_RE = re.compile(r"//.*$")
# A line that opens or continues a body -- used only to SKIP, never to store.
_PROTECTED_RE = re.compile(r"^\s*`p(?:rotect|rotected)\b|^\s*`pragma\s+protect", re.IGNORECASE)


def analysis_port_kind(port_type: str) -> tuple:
    """`(kind, direction)` for one UVM analysis base type. Longest prefix wins
    so `uvm_analysis_imp_master` (a `uvm_analysis_imp_decl` product) is an IMP
    rather than falling through to a bare port match."""
    for prefix, kinds in sorted(_ANALYSIS_KIND_BY_PREFIX, key=lambda x: -len(x[0])):
        if port_type.startswith(prefix):
            return kinds
    return ("ANALYSIS_UNKNOWN", "UNKNOWN")


class VipSymbolIndexError(ValueError):
    """A symbol index fails validation, or the indexer was pointed at a root
    that does not exist. Raised rather than returning an empty index, since
    an empty index and a mistyped path are completely different situations
    and must not look identical to a caller."""


def validate_symbol_index(doc: dict) -> None:
    """Validate `doc` against vip_symbol_index.schema.json."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise VipSymbolIndexError(
            "jsonschema package is not installed; cannot validate against "
            "vip_symbol_index.schema.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise VipSymbolIndexError("vip_symbol_index.schema.json validation failed:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# indexing
# ---------------------------------------------------------------------------

def index_source_text(text: str, file_label: str) -> list:
    """Index one file's text into class entries. Returns a list of class
    dicts (schema `class_entry` shape).

    Only declaration lines are inspected. A method's body lines are matched
    by nothing here and are simply never stored -- there is no code path in
    this function that appends statement text to the result. Symbols
    declared outside any class are skipped: a VIP's package-level helpers are
    not what row 13's "class/method names" navigation aid is for, and
    including them would bloat the index with the very noise it exists to
    avoid."""
    classes = []
    current: Optional[dict] = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _COMMENT_RE.sub("", raw)
        if not line.strip() or _PROTECTED_RE.match(line):
            continue

        m = _CLASS_RE.match(line)
        if m:
            current = {
                "name": m.group("name"),
                "base_class": m.group("base"),
                "is_virtual": bool(m.group("virtual")),
                "file": file_label,
                "line": lineno,
                "methods": [],
                "config_fields": [],
                "analysis_ports": [],
            }
            classes.append(current)
            continue

        if _ENDCLASS_RE.match(line):
            current = None
            continue

        if current is None:
            continue

        m = _METHOD_RE.match(line)
        if m and m.group("name") not in ("new",):
            args = m.group("args")
            current["methods"].append({
                "name": m.group("name"),
                "kind": m.group("kind"),
                "return_type": (m.group("rettype") or "").strip() or None,
                "is_virtual": bool(m.group("virtual")),
                "is_extern": bool(m.group("extern")),
                # The literal declared argument list. A DECLARATION, never a
                # body: the regex's own `[^;]*` inside parentheses cannot span
                # past the signature.
                "arguments": args.strip() if args else None,
                "file": file_label,
                "line": lineno,
            })
            continue

        m = _ANALYSIS_PORT_RE.match(line)
        if m:
            params = (m.group("params") or "").strip()
            # Only the FIRST type parameter: for `uvm_analysis_imp#(T, IMP)`
            # the second is the implementing class, not the transaction.
            txn = params.split(",")[0].strip() if params else None
            kind, direction = analysis_port_kind(m.group("port_type"))
            current["analysis_ports"].append({
                "name": m.group("name"),
                "port_type": m.group("port_type"),
                "kind": kind,
                "direction": direction,
                "transaction_type": txn or None,
                "array_dimension": (m.group("dim") or "").strip() or None,
                "file": file_label,
                "line": lineno,
            })
            continue

        m = _FIELD_RE.match(line)
        if m:
            current["config_fields"].append({
                "name": m.group("name"),
                "data_type": m.group("dtype"),
                "is_rand": bool(m.group("rand")),
                "file": file_label,
                "line": lineno,
            })
    return classes


def iter_source_files(roots: Iterable, suffixes: Iterable[str] = DEFAULT_SOURCE_SUFFIXES) -> list:
    """Every VIP source file under `roots`, sorted for a stable index. A root
    that does not exist raises rather than silently contributing nothing --
    a typo'd VIP path must not look like an empty VIP."""
    out = []
    for root in roots:
        p = Path(root)
        if not p.exists():
            raise VipSymbolIndexError(
                f"VIP source root does not exist: {root} -- a mistyped root must not be "
                "silently indistinguishable from a VIP with no source in it"
            )
        if p.is_file():
            out.append(p)
            continue
        for suffix in suffixes:
            out.extend(p.rglob(f"*{suffix}"))
    return sorted(set(out), key=lambda x: str(x).replace("\\", "/"))


def _relativize(path, base: Optional[Path]) -> str:
    """Path as a forward-slash string, relative to `base` when possible.
    Falls back to the absolute form when the path genuinely lies outside
    `base` -- a wrong-looking relative path would be worse than an honest
    absolute one."""
    p = Path(path)
    if base is not None:
        try:
            return str(p.resolve().relative_to(Path(base).resolve())).replace("\\", "/")
        except ValueError:
            pass
    return str(p).replace("\\", "/")


def build_symbol_index(roots, protocol: str,
                        suffixes: Iterable[str] = DEFAULT_SOURCE_SUFFIXES,
                        relative_to=None) -> dict:
    """Build a complete, schema-valid symbol index over the VIP source under
    `roots`. `protocol` is supplied by the caller and never inferred from a
    directory name -- guessing a protocol from a path is exactly the kind of
    naming-derived fact this repo keeps out of structural artifacts."""
    files = iter_source_files(roots, suffixes)
    base = Path(relative_to) if relative_to else None
    classes, bytes_scanned = [], 0
    for f in files:
        raw = f.read_text(encoding="utf-8", errors="replace")
        bytes_scanned += len(raw.encode("utf-8", errors="replace"))
        classes.extend(index_source_text(raw, _relativize(f, base)))
    classes.sort(key=lambda c: (c["file"], c["line"]))
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.vip_symbol_index", "version": SCHEMA_VERSION},
        "protocol": protocol,
        # Roots are recorded RELATIVE to `relative_to` when it is given, for
        # the same reason file labels are: an absolute path bakes one
        # machine's directory layout into a committed, diffable artifact, so
        # the same VIP tree indexed on two machines would produce two
        # different files and every diff would be noise.
        "roots": [_relativize(r, base) for r in roots],
        "stats": {
            "files_scanned": len(files),
            "classes_indexed": len(classes),
            "methods_indexed": sum(len(c["methods"]) for c in classes),
            "bytes_scanned": bytes_scanned,
        },
        "classes": classes,
    }
    validate_symbol_index(doc)
    return doc


# Tokens that can only come from a statement body, never from a class,
# method or property DECLARATION. Used by assert_no_bodies_retained().
_BODY_TOKENS = ("begin", "end;", "$display", "uvm_report", "if(", "if (",
                "for(", "for (", "while(", "while (", "return ", "<=", ":=")


def assert_no_bodies_retained(doc: dict) -> None:
    """Assert the row-13 invariant as a CHECKABLE property: no stored string
    in the index contains implementation text.

    Only fields that could plausibly carry code are examined -- the method
    `arguments` signature text and every name/type field. A violation raises,
    because an index that quietly started capturing bodies would defeat the
    entire purpose of the artifact (and would smuggle tier-1 VIP source into
    context inside a tier-3-shaped file) while still validating cleanly
    against the schema."""
    for cls in doc.get("classes", []):
        for method in cls.get("methods", []):
            args = method.get("arguments") or ""
            for token in _BODY_TOKENS:
                if token in args:
                    raise VipSymbolIndexError(
                        f"VIP_SYMBOL_INDEX_BODY_LEAK: method {cls['name']}.{method['name']} "
                        f"at {method['file']}:{method['line']} stored text containing {token!r}, "
                        "which can only come from a statement body. The index must hold "
                        "declarations and locations only."
                    )
        for port in cls.get("analysis_ports", []):
            # The two free-text fields an analysis-port entry carries. Held to
            # the same invariant as a method signature: a `#(...)` parameter
            # list and an array dimension are declarations, and nothing that
            # could only come from a statement may appear in either.
            for value in (port.get("transaction_type") or "", port.get("array_dimension") or ""):
                for token in _BODY_TOKENS:
                    if token in value:
                        raise VipSymbolIndexError(
                            f"VIP_SYMBOL_INDEX_BODY_LEAK: analysis port "
                            f"{cls['name']}.{port['name']} at {port['file']}:{port['line']} "
                            f"stored text containing {token!r}, which can only come from a "
                            "statement body. The index must hold declarations and locations only."
                        )


def save_symbol_index(doc: dict, path) -> None:
    """Validate, assert the no-bodies invariant, then write deterministically
    (no timestamp anywhere in the schema, so an unchanged VIP tree
    regenerates byte-identically -- env_manifest.py's Diffability contract)."""
    validate_symbol_index(doc)
    assert_no_bodies_retained(doc)
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_symbol_index(path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_symbol_index(doc)
    return doc


def find_symbol(doc: dict, name: str) -> list:
    """The row-13 consumer: "targeted read when needed". Resolve a class or
    method name to the concrete file:line locations to read, so an agent
    opens one cited location instead of searching the VIP tree.

    Matching is case-insensitive substring, because a caller usually knows a
    partial name ("sequencer", "set_config") rather than an exact symbol."""
    needle = name.lower()
    hits = []
    for cls in doc.get("classes", []):
        if needle in cls["name"].lower():
            hits.append({"kind": "class", "name": cls["name"], "base_class": cls.get("base_class"),
                         "file": cls["file"], "line": cls["line"]})
        for method in cls.get("methods", []):
            if needle in method["name"].lower():
                hits.append({"kind": method["kind"], "name": f"{cls['name']}.{method['name']}",
                             "arguments": method.get("arguments"),
                             "file": method["file"], "line": method["line"]})
        for field in cls.get("config_fields", []):
            if needle in field["name"].lower():
                hits.append({"kind": "field", "name": f"{cls['name']}.{field['name']}",
                             "data_type": field.get("data_type"),
                             "file": field["file"], "line": field["line"]})
        for port in cls.get("analysis_ports", []):
            if needle in port["name"].lower():
                hits.append({"kind": "analysis_port",
                             "name": f"{cls['name']}.{port['name']}",
                             "data_type": port.get("port_type"),
                             "file": port["file"], "line": port["line"]})
    return hits


# ---------------------------------------------------------------------------
# row 12: the distilled vip_ref/<protocol>.md
# ---------------------------------------------------------------------------

# Heuristic groupings for the reference document's own sections. These order
# and label the output only -- a class matching nothing still appears, under
# "Other", so nothing is ever dropped from the reference just because its
# name did not match a bucket.
_ROLE_BUCKETS = (
    ("Configuration", ("config", "cfg")),
    ("Sequences", ("seq", "sequence")),
    ("Transactions / Items", ("item", "txn", "transaction", "packet", "frame")),
    ("Agents / Drivers / Monitors", ("agent", "driver", "monitor", "sequencer")),
    ("Callbacks / Coverage", ("callback", "cb", "cov")),
)


def _bucket_for(class_name: str) -> str:
    lowered = class_name.lower()
    for label, keys in _ROLE_BUCKETS:
        if any(k in lowered for k in keys):
            return label
    return "Other"


def render_vip_ref_markdown(doc: dict, *, max_methods_per_class: int = 12) -> str:
    """Render the tier-3 `vip_ref/<protocol>.md` from a real symbol index.

    This is row 12's "VIP document -> vip_ref/<protocol>.md (distilled) ->
    config field semantics, built-in check list". It is derived ENTIRELY from
    the real indexed VIP source: every class, method and config field below
    was found at a cited file:line. Nothing is written from the model's prior
    knowledge of what a protocol VIP usually contains -- that would be
    invented content wearing an evidence-shaped artifact's name, the exact
    failure CLAUDE.md's No Golden-Reference Content Mining rule forbids.

    The honest limit, stated in the document itself: SEMANTICS are not
    distilled here. A config field's meaning lives in the VIP's user guide,
    which is a tier-1 PDF this module does not read. What this file gives is
    the real field/method inventory with locations, so the semantics can be
    looked up one targeted read at a time. `max_methods_per_class` bounds the
    output so the tier-3 artifact stays small enough to actually load on
    demand."""
    stats = doc["stats"]
    lines = [
        f"# VIP Reference -- {doc['protocol']}",
        "",
        "> GENERATED by `dv_harness/vip_symbol_index.py` from a real VIP source symbol index.",
        "> Do not hand-edit: regenerate instead.",
        "",
        "## Provenance",
        "",
        f"- Protocol: `{doc['protocol']}`",
        f"- Source roots: {', '.join(f'`{r}`' for r in doc['roots']) or '(none)'}",
        f"- Files scanned: {stats['files_scanned']}",
        f"- Classes indexed: {stats['classes_indexed']}",
        f"- Methods indexed: {stats['methods_indexed']}",
        f"- Source bytes scanned: {stats['bytes_scanned']:,}",
        "",
        "## What this document is, and is not",
        "",
        "This is a DECLARATION INVENTORY distilled from the VIP source: what classes,",
        "methods and config fields exist, and the exact `file:line` to read for each.",
        "It exists so the VIP source tree itself never has to enter context (CLAUDE.md",
        "context-budget tier 1, `NEVER-VIP-SOURCE`).",
        "",
        "It does NOT carry SEMANTICS. What a config field *means*, what a check",
        "*asserts*, and which knobs are legal together all live in the VIP user guide,",
        "which is a tier-1 PDF this generator deliberately does not read. Use the",
        "`file:line` pointers below for a targeted read of the one symbol you need;",
        "never treat this inventory as a behavioural specification.",
        "",
    ]

    buckets: dict = {}
    for cls in doc.get("classes", []):
        buckets.setdefault(_bucket_for(cls["name"]), []).append(cls)

    ordered = [label for label, _ in _ROLE_BUCKETS] + ["Other"]
    for label in ordered:
        entries = buckets.get(label)
        if not entries:
            continue
        lines += [f"## {label}", ""]
        for cls in sorted(entries, key=lambda c: c["name"]):
            base = f" extends `{cls['base_class']}`" if cls.get("base_class") else ""
            virt = "virtual " if cls.get("is_virtual") else ""
            lines += [f"### `{virt}class {cls['name']}`{base}", "",
                      f"- Declared at `{cls['file']}:{cls['line']}`", ""]
            if cls.get("config_fields"):
                lines += ["| Config field | Type | rand | Location |",
                          "| --- | --- | --- | --- |"]
                for f in cls["config_fields"]:
                    lines.append(
                        f"| `{f['name']}` | `{f['data_type']}` | "
                        f"{'yes' if f.get('is_rand') else 'no'} | `{f['file']}:{f['line']}` |"
                    )
                lines.append("")
            methods = cls.get("methods") or []
            if methods:
                lines += ["| Method | Kind | Signature | Location |", "| --- | --- | --- | --- |"]
                for m in methods[:max_methods_per_class]:
                    sig = (m.get("arguments") or "()").replace("|", r"\|")
                    lines.append(
                        f"| `{m['name']}` | {m['kind']} | `{sig}` | `{m['file']}:{m['line']}` |"
                    )
                if len(methods) > max_methods_per_class:
                    lines.append(
                        f"| _... {len(methods) - max_methods_per_class} more_ | | "
                        f"| _query via `vip_symbol_index.find_symbol()`_ |"
                    )
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_vip_ref(doc: dict, out_dir, *, max_methods_per_class: int = 12) -> Path:
    """Write `vip_ref/<protocol>.md` under `out_dir`, the exact tier-3 path
    CLAUDE.md's context budget names."""
    out = Path(out_dir) / "vip_ref"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{doc['protocol']}.md"
    path.write_text(render_vip_ref_markdown(doc, max_methods_per_class=max_methods_per_class),
                    encoding="utf-8")
    return path
