"""dv_harness/doc_extraction_fanout.py -- dispatch this repo's real document
extractors CONCURRENTLY across self_check_list.md item #40's eleven document
categories.

WHY THIS EXISTS
---------------
Item #40 asks for multiple extraction workers launched SIMULTANEOUSLY to
convert the eleven document categories a VIP-based verification environment is
built out of (VIP doc/source/examples, DUT doc/registers, IP doc, programming
guide, DUT RTL, IP source, top TB, command.txt, standard specs). A 2026-09-05
audit confirmed the INDIVIDUAL extractors are real -- `vip_user_guide_distill`,
`vip_symbol_index`, `design_intent`, `init_seq`, `env_manifest`,
`makefile_to_run_profile`, `reference_pattern_audit` -- and that the DISPATCH
LAYER did not exist anywhere:

  - `.dv-harness/graph/main_graph.json` has exactly two non-null
    `parallel_group`s (ANALYSIS_G1, RCA_G1); neither is document extraction;
  - `.claude/workflows/` holds exactly two scripts, both for RCA/evidence
    consensus, and neither references any of the extractor modules;
  - a repo-wide grep for the extractor module names inside `dv_harness/*.py`
    found only sequential single-purpose imports for one specific downstream
    consumer at a time.

So each extractor was only ever invoked individually, on its own CLI verb or by
a direct import. This module is the missing fan-out, and nothing else.

WHAT IT REUSES RATHER THAN REBUILDS
-----------------------------------
- **The concurrency pattern is `subsystem_architecture_analysis.
  run_per_subsystem_analyses()`'s**, deliberately: one `ThreadPoolExecutor`
  over a list of independent read-only units of work, results collected and
  then sorted into a DETERMINISTIC declared order so a fan-out's output never
  depends on which worker finished first. No new concurrency primitive is
  introduced, and no `parallel_group` graph node is added -- these extractors
  are not graph stages and inventing a stage for them would put document
  conversion on the verification closure path.
- **Every extractor is called, never reimplemented.** `CATEGORY_EXTRACTORS`
  holds one thin adapter per category whose entire job is to map this module's
  uniform `ExtractionRequest` onto that extractor's own real signature.
- **`doc_extraction.DocumentIndex` gets its first pipeline caller.** That
  module's own NOTICE has said since 2026-08-28 that "no stage in
  dv_harness/engine.py and no .claude/agents/*.md profile invokes
  DocumentIndex, needs_extract(), register()". The fan-out registers every
  SOURCE document it consumes into that same index (`kind` =
  `doc_extraction:<category_id>`), so provenance for a converted document is
  recorded in the one index this repo already has, and `--incremental` can ask
  `needs_extract()` whether a source really changed instead of re-converting a
  200-page PDF on every run.

WHAT COUNTS AS A CATEGORY IS DATA
---------------------------------
`doc_extraction_categories.json`, beside this file. Extend the JSON for a
project's own categories, never this Python.
`assert_extractor_table_matches_categories()` holds the two together: a
category declaring an extractor with no adapter, an adapter for no category, or
a declared `module.callable` that no longer resolves through the import system,
each fail a test rather than silently dropping a category out of the fan-out.

FOUR PROPERTIES, EACH ENFORCED IN CODE AND EACH TESTED
-------------------------------------------------------
1. **An absent extractor is REPORTED, never faked.** Two of item #40's eleven
   categories genuinely have no extractor here (40c VIP examples, 40h IP
   source) and report `NO_EXTRACTOR` carrying the real reason from the JSON. A
   category with an extractor but no inputs reports `INPUT_NOT_SUPPLIED`. Those
   are three distinct facts -- "nobody built this", "you gave me nothing", and
   "it ran" -- and collapsing any two of them would let an empty fan-out read
   as a complete one.
2. **One failing category never sinks the fan-out.** Each unit is isolated: a
   raising extractor is recorded as `FAILED` with its real exception type and
   message, and the other ten still run. A fan-out that aborted on the first
   bad document would be strictly worse than the sequential status quo.
3. **Concurrent writes cannot collide.** Every category writes into its OWN
   `<out_root>/<category_id>/` directory, asserted distinct before any worker
   starts. The one genuinely shared mutable resource is
   `DocumentIndex.register()`, a read-modify-write over a single JSON file, so
   it is serialized behind `_INDEX_LOCK`. This is a real hazard, not a
   defensive one: without the lock, concurrent registration of nine categories'
   source documents loses rows.
4. **Reading is never a mutating act.** No adapter escalates to the question
   queue, writes a Blackboard topic, mints an approval, or touches memory --
   even where the underlying extractor supports it (`audit_directory()` takes a
   `question_store=`; the fan-out never passes one). Converting a pile of
   documents must not be the thing that quietly files eleven questions for a
   human.
"""
from __future__ import annotations

import importlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .doc_extraction import DocumentIndex, sha256_file

SCHEMA_VERSION = "1.0"

CATEGORIES_PATH = Path(__file__).resolve().parent / "doc_extraction_categories.json"

# The per-category outcome vocabulary. Deliberately NOT any member of
# models.Status: a document conversion is not a stage-gate verdict, and a
# fan-out result must never be mistakable for one by a caller that branches on
# Status members.
STATUS_EXTRACTED = "EXTRACTED"
STATUS_UP_TO_DATE = "UP_TO_DATE"
STATUS_INPUT_NOT_SUPPLIED = "INPUT_NOT_SUPPLIED"
STATUS_NO_EXTRACTOR = "NO_EXTRACTOR"
STATUS_FAILED = "FAILED"
EXTRACTION_STATUSES = (
    STATUS_EXTRACTED,
    STATUS_UP_TO_DATE,
    STATUS_INPUT_NOT_SUPPLIED,
    STATUS_NO_EXTRACTOR,
    STATUS_FAILED,
)

# DocumentIndex row `kind` prefix, so a document ingested by the fan-out stays
# distinguishable in the shared index from a research_document or a
# register/PHY document.
INDEX_KIND_PREFIX = "doc_extraction"

# Serializes DocumentIndex.register(), which is a read-modify-write over one
# JSON file. See property 3 in this module's docstring.
_INDEX_LOCK = threading.Lock()


class DocExtractionFanoutError(RuntimeError):
    """The fan-out cannot be dispatched as requested -- an unknown category id,
    a category-table/adapter-table disagreement, or an output layout in which
    two categories would write the same directory. Raised rather than returned
    so a malformed fan-out never produces a partial result set a reader would
    take for a complete one."""


# ---------------------------------------------------------------------------
# category table (data) + adapter table (code), held together by a drift check
# ---------------------------------------------------------------------------

def load_categories() -> List[dict]:
    """The eleven declared categories, in declaration order. Read from
    `doc_extraction_categories.json` rather than duplicated here so this
    module cannot drift from the contract it dispatches against."""
    doc = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    return list(doc["categories"])


def category_ids() -> tuple:
    return tuple(c["category_id"] for c in load_categories())


def category(category_id: str) -> dict:
    for entry in load_categories():
        if entry["category_id"] == category_id:
            return entry
    raise DocExtractionFanoutError(
        f"unknown document category {category_id!r}; declared categories are "
        f"{list(category_ids())}")


@dataclass(frozen=True)
class ExtractionRequest:
    """What one category's adapter is handed. Uniform on purpose: the eleven
    extractors have eleven different signatures, and the adapter -- not the
    caller and not the JSON -- is where that difference lives.

    Deliberately carries only what an adapter actually reads. The project root
    is NOT on it: the DocumentIndex is owned by the dispatcher, no adapter
    resolves a path against the project, and a field nothing reads is exactly
    the unreached surface `doc_extraction.py`'s own NOTICE is about."""

    category_id: str
    inputs: Mapping[str, Any]
    out_dir: Path

    def required(self, key: str) -> Any:
        if key not in self.inputs or self.inputs[key] in (None, "", [], {}):
            raise DocExtractionFanoutError(
                f"category {self.category_id!r}: required input {key!r} was not supplied")
        return self.inputs[key]

    def optional(self, key: str, default=None) -> Any:
        value = self.inputs.get(key, default)
        return default if value in (None, "", [], {}) else value


@dataclass
class ExtractionOutcome:
    """One category's real result. `source_documents` are the input files the
    extractor actually consumed -- what gets registered in the DocumentIndex --
    and `artifacts` are the files it actually wrote."""

    artifacts: List[Path] = field(default_factory=list)
    source_documents: List[Path] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)


# --- adapters: one per category that has a real extractor -------------------
#
# Each adapter's ONLY job is to map ExtractionRequest onto one real extractor's
# own signature and report what it produced. No adapter contains extraction
# logic of its own; if one ever needs to, that logic belongs in the extractor
# module where its own tests can reach it.

def _extract_user_guides(req: ExtractionRequest, doc_kind: str) -> ExtractionOutcome:
    from .vip_user_guide_distill import distill_user_guide

    out = ExtractionOutcome()
    specs = [{"path": s} if isinstance(s, str) else dict(s)
             for s in req.required("documents")]
    # distill_user_guide() names all three of its artifacts `<stem>.*` in the
    # SAME output directory, so two documents whose stems collide would
    # silently overwrite each other's extraction. Refused up front rather than
    # discovered as a reference.json describing the wrong document.
    stems = [Path(s["path"]).stem for s in specs]
    duplicates = sorted({s for s in stems if stems.count(s) > 1})
    if duplicates:
        raise DocExtractionFanoutError(
            f"category {req.category_id!r}: documents with colliding file stems "
            f"{duplicates} would overwrite each other's <stem>.fulltext.txt / "
            "<stem>.reference.json / <stem>.reference.md")
    for spec in specs:
        source = Path(spec["path"])
        record = distill_user_guide(
            source, req.out_dir, title=spec.get("title"),
            doc_kind=spec.get("doc_kind", doc_kind))
        out.source_documents.append(source)
        out.artifacts.append(Path(record["full_text_extract"]["path"]))
        out.artifacts.append(Path(record["distilled_reference"]["path"]))
        out.artifacts.append(req.out_dir / f"{source.stem}.reference.json")
        out.detail.setdefault("documents", []).append({
            "source": str(source),
            "doc_kind": record.get("doc_kind"),
            "page_count": (record.get("source_document") or {}).get("page_count"),
            "section_count": record.get("section_count"),
        })
    return out


def _adapter_vip_user_guide(req: ExtractionRequest) -> ExtractionOutcome:
    return _extract_user_guides(req, "vip_user_guide")


def _adapter_standard_spec(req: ExtractionRequest) -> ExtractionOutcome:
    return _extract_user_guides(req, "protocol_spec")


def _adapter_vip_source(req: ExtractionRequest) -> ExtractionOutcome:
    from . import vip_symbol_index

    roots = req.required("roots")
    roots = [roots] if isinstance(roots, (str, Path)) else list(roots)
    protocol = req.required("protocol")
    doc = vip_symbol_index.build_symbol_index(
        roots, protocol, relative_to=req.optional("relative_to"))
    # The invariant that makes indexing a context-budget tier-1 tree legitimate
    # at all. Asserted here too, not only inside the builder, because the
    # fan-out is the path that will point this at a real customer VIP tree.
    vip_symbol_index.assert_no_bodies_retained(doc)
    index_path = req.out_dir / "vip_symbol_index.json"
    vip_symbol_index.save_symbol_index(doc, index_path)
    ref_path = vip_symbol_index.write_vip_ref(doc, req.out_dir)
    return ExtractionOutcome(
        artifacts=[index_path, ref_path],
        source_documents=[Path(f) for f in vip_symbol_index.iter_source_files(roots)],
        detail={"protocol": protocol, "class_count": len(doc.get("classes") or [])},
    )


def _adapter_dut_document_registers(req: ExtractionRequest) -> ExtractionOutcome:
    from . import design_intent, sys_regmap

    out = ExtractionOutcome()
    intent_path = Path(req.required("intent_path"))
    intent_doc = design_intent.load_intent(intent_path)
    out.artifacts.append(design_intent.write_intent(intent_doc, req.out_dir))
    out.source_documents.append(intent_path)
    out.detail["dut_name"] = intent_doc.get("dut_name")

    regmap_path = req.optional("sys_regmap_path")
    if regmap_path:
        regmap_path = Path(regmap_path)
        regmap_doc = sys_regmap.load_sys_regmap(regmap_path)
        bits = sys_regmap.mode_determining_bits(regmap_doc)
        bits_path = req.out_dir / "sys_regmap.mode_bits.json"
        bits_path.write_text(
            json.dumps({"source": str(regmap_path), "mode_determining_bits": bits},
                        ensure_ascii=False, indent=2), encoding="utf-8")
        out.artifacts.append(bits_path)
        out.source_documents.append(regmap_path)
        out.detail["mode_determining_bit_count"] = len(bits)
    else:
        # Stated, not silent: the register half of category 40d was not
        # supplied, and the caller must be able to tell that from the result
        # rather than from a missing filename.
        out.detail["sys_regmap"] = "NOT_SUPPLIED"
    return out


def _adapter_ip_document(req: ExtractionRequest) -> ExtractionOutcome:
    from . import design_intent

    path = Path(req.required("constraints_path"))
    doc = design_intent.load_constraints(path)
    return ExtractionOutcome(
        artifacts=[design_intent.write_constraints(doc, req.out_dir)],
        source_documents=[path],
        detail={"ip_name": doc.get("ip_name"),
                "untestable_item_count": len(doc.get("untestable_items") or [])},
    )


def _adapter_programming_guide(req: ExtractionRequest) -> ExtractionOutcome:
    from . import init_seq, sys_regmap

    path = Path(req.required("init_seq_path"))
    doc = init_seq.load_init_seq(path)
    sources = [path]
    regmap_doc = None
    regmap_path = req.optional("sys_regmap_path")
    if regmap_path:
        regmap_path = Path(regmap_path)
        regmap_doc = sys_regmap.load_sys_regmap(regmap_path)
        sources.append(regmap_path)
    steps = init_seq.directed_test_steps(doc, regmap_doc)
    steps_path = req.out_dir / "init_seq.directed_steps.json"
    steps_path.write_text(
        json.dumps({"source": str(path),
                     "interface": doc.get("interface"),
                     "address_resolution": "sys_regmap" if regmap_doc else "NOT_RESOLVED_NO_REGMAP",
                     "steps": steps}, ensure_ascii=False, indent=2), encoding="utf-8")
    return ExtractionOutcome(artifacts=[steps_path], source_documents=sources,
                              detail={"step_count": len(steps)})


def _adapter_dut_rtl(req: ExtractionRequest) -> ExtractionOutcome:
    from . import env_manifest

    out_path = req.out_dir / "env.manifest.json"
    rtl_files = req.optional("rtl_files") or []
    rtl_files = [rtl_files] if isinstance(rtl_files, (str, Path)) else list(rtl_files)
    kwargs = {"rtl_files": rtl_files or None}
    for key in ("register_map_path", "soc_arch_map_path", "testplan_sources_path",
                "vip_config_dump_path", "topology_dump_path",
                "config_db_trace_log_path", "designware_home"):
        value = req.optional(key)
        if value:
            kwargs[key] = value
    verible_bin = req.optional("verible_bin")
    if verible_bin:
        kwargs["verible_bin"] = verible_bin
    manifest = env_manifest.generate_and_write(out_path, **kwargs)
    sources = [Path(f) for f in rtl_files]
    for key in ("register_map_path", "soc_arch_map_path", "testplan_sources_path"):
        if req.optional(key):
            sources.append(Path(req.optional(key)))
    return ExtractionOutcome(
        artifacts=[out_path],
        source_documents=sources,
        # Each layer's OWN honest status is carried through verbatim -- a
        # NOT_AVAILABLE rtl layer (no verible binary) must never be summarized
        # away into a fan-out that reports a clean EXTRACTED and nothing else.
        detail={"layer_status": {
            "rtl": (manifest.get("dut_facts", {}).get("rtl") or {}).get("status"),
            "registers": (manifest.get("dut_facts", {}).get("registers") or {}).get("status"),
            "address_map": (manifest.get("dut_facts", {}).get("address_map") or {}).get("status"),
            "clock_reset": (manifest.get("dut_facts", {}).get("clock_reset") or {}).get("status"),
            "vip_config": (manifest.get("vip_config") or {}).get("status"),
        }},
    )


def _adapter_top_testbench_runscript(req: ExtractionRequest) -> ExtractionOutcome:
    from .uvm_generator.makefile_to_run_profile import extract_and_write

    makefile = Path(req.required("makefile"))
    out_path = req.out_dir / "run_profile.json"
    profile = extract_and_write(makefile, out_path,
                                 target_ip=req.required("target_ip"),
                                 ip_prefix=req.required("ip_prefix"))
    return ExtractionOutcome(
        artifacts=[out_path], source_documents=[makefile],
        # hierarchy.json is category 40i's other half and has no non-agent
        # extractor (CLAUDE.md's Context Budget section). Said here so a reader
        # of a fan-out result is not left assuming it was produced.
        detail={"target_count": len(profile.get("targets") or []),
                 "hierarchy_json": "NOT_PRODUCED_NO_NON_AGENT_EXTRACTOR"},
    )


def _adapter_reference_command_txt(req: ExtractionRequest) -> ExtractionOutcome:
    from .reference_pattern_audit import audit_directory

    pattern_dir = Path(req.required("pattern_dir"))
    glob = req.optional("glob", "*.txt")
    # question_store is deliberately NOT passed -- see property 4.
    result = audit_directory(pattern_dir, glob=glob)
    out_path = req.out_dir / "reference_pattern_audit.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sources = sorted(p for p in pattern_dir.glob(glob) if p.is_file())
    return ExtractionOutcome(
        artifacts=[out_path], source_documents=sources,
        detail={"files_audited": len(sources),
                 "escalated_to_question_queue": False},
    )


CATEGORY_EXTRACTORS: Dict[str, Callable[[ExtractionRequest], ExtractionOutcome]] = {
    "vip_user_guide": _adapter_vip_user_guide,
    "vip_source": _adapter_vip_source,
    "dut_document_registers": _adapter_dut_document_registers,
    "ip_document": _adapter_ip_document,
    "programming_guide": _adapter_programming_guide,
    "dut_rtl": _adapter_dut_rtl,
    "top_testbench_runscript": _adapter_top_testbench_runscript,
    "reference_command_txt": _adapter_reference_command_txt,
    "standard_spec": _adapter_standard_spec,
}


def assert_extractor_table_matches_categories() -> None:
    """`CATEGORY_EXTRACTORS` must cover exactly the categories declaring an
    extractor, and every declared `module.callable` must really resolve.

    Both directions matter. A category added to the JSON with no adapter would
    silently drop out of every fan-out; an adapter for a category nobody
    declared would never be dispatched; and a declared callable that was
    renamed would leave the JSON describing an extractor that no longer exists,
    which is the documentation-drift failure this repo keeps failing a test
    over rather than discovering in a report.
    """
    declared = {c["category_id"] for c in load_categories() if c.get("extractor")}
    implemented = set(CATEGORY_EXTRACTORS)
    if declared != implemented:
        raise DocExtractionFanoutError(
            "doc_extraction_categories.json and CATEGORY_EXTRACTORS disagree -- "
            f"declared-but-no-adapter: {sorted(declared - implemented)}; "
            f"adapter-but-not-declared: {sorted(implemented - declared)}")
    for entry in load_categories():
        target = entry.get("extractor")
        if not target:
            if not entry.get("no_extractor_reason"):
                raise DocExtractionFanoutError(
                    f"category {entry['category_id']!r} declares no extractor and no "
                    "no_extractor_reason -- an absent capability must say why it is absent")
            continue
        module_name, _, attr = target.rpartition(".")
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise DocExtractionFanoutError(
                f"category {entry['category_id']!r} names extractor {target!r}, whose "
                f"module does not import: {exc}") from exc
        if not callable(getattr(module, attr, None)):
            raise DocExtractionFanoutError(
                f"category {entry['category_id']!r} names extractor {target!r}, which "
                f"does not resolve to a callable on {module_name}")


# ---------------------------------------------------------------------------
# planning (no work performed) and dispatch (the fan-out itself)
# ---------------------------------------------------------------------------

def _resolve_selection(only: Optional[Sequence[str]]) -> List[dict]:
    entries = load_categories()
    if not only:
        return entries
    wanted = list(only)
    known = set(category_ids())
    unknown = [c for c in wanted if c not in known]
    if unknown:
        raise DocExtractionFanoutError(
            f"unknown document categories {unknown}; declared categories are "
            f"{list(category_ids())}")
    return [e for e in entries if e["category_id"] in set(wanted)]


def plan_extractions(inputs: Mapping[str, Any],
                     *, only: Optional[Sequence[str]] = None) -> List[dict]:
    """What a `dispatch_document_extractions()` call WOULD do, performing no
    extraction and touching no file. The three non-running outcomes
    (NO_EXTRACTOR / INPUT_NOT_SUPPLIED / would-run) are decidable without
    opening a single document, which is what makes a dry run honest."""
    plan = []
    for entry in _resolve_selection(only):
        cid = entry["category_id"]
        if not entry.get("extractor"):
            status, reason = STATUS_NO_EXTRACTOR, entry.get("no_extractor_reason")
        elif not inputs.get(cid):
            status, reason = STATUS_INPUT_NOT_SUPPLIED, (
                f"no inputs supplied for category {cid!r}; expected keys "
                f"{entry.get('input_keys') or []}")
        else:
            status, reason = "WOULD_EXTRACT", None
        plan.append({"category_id": cid, "checklist_item": entry.get("checklist_item"),
                      "title": entry.get("title"), "extractor": entry.get("extractor"),
                      "status": status, "reason": reason})
    return plan


def _register_sources(index: Optional[DocumentIndex], category_id: str,
                      sources: Sequence[Path]) -> List[dict]:
    """Record every consumed source document in the shared DocumentIndex.

    Serialized behind `_INDEX_LOCK`: `DocumentIndex.register()` reads the whole
    index, appends, and rewrites it, so concurrent registration from nine
    workers loses rows without this.
    """
    rows = []
    if index is None:
        return rows
    for source in sources:
        source = Path(source)
        if not source.is_file():
            continue
        with _INDEX_LOCK:
            row = index.register(source, kind=f"{INDEX_KIND_PREFIX}:{category_id}")
        rows.append({"path": row["path"], "sha256": row["sha256"]})
    return rows


def _sources_unchanged(index: Optional[DocumentIndex], sources: Sequence[Path]) -> bool:
    """True when every source is already in the index with a matching sha256.

    The index is SNAPSHOT under the lock and the hashing is done outside it --
    `DocumentIndex.needs_extract()` re-reads the whole index and re-hashes the
    file on every call, so calling it under `_INDEX_LOCK` would serialize every
    worker behind the sha256 of a possibly-200-page PDF. The lock exists to
    make the read-modify-write in `_register_sources()` atomic, not to make
    reads slow.
    """
    if index is None or not sources:
        return False
    with _INDEX_LOCK:
        known = {row.get("path"): row.get("sha256") for row in index.load()}
    for source in sources:
        source = Path(source)
        if not source.is_file():
            return False
        if known.get(str(source.resolve())) != sha256_file(source):
            return False
    return True


def _declared_sources(entry: dict, inputs: Mapping[str, Any]) -> List[Path]:
    """The source files a category's inputs NAME, derived from the inputs alone
    so `--incremental` can decide to skip without running the extractor."""
    cid_inputs = dict(inputs.get(entry["category_id"]) or {})
    out: List[Path] = []
    for spec in cid_inputs.get("documents") or []:
        out.append(Path(spec if isinstance(spec, str) else spec["path"]))
    for key in ("intent_path", "sys_regmap_path", "constraints_path", "init_seq_path",
                "makefile", "register_map_path", "soc_arch_map_path",
                "testplan_sources_path"):
        if cid_inputs.get(key):
            out.append(Path(cid_inputs[key]))
    rtl = cid_inputs.get("rtl_files") or []
    out.extend(Path(f) for f in ([rtl] if isinstance(rtl, (str, Path)) else rtl))
    roots = cid_inputs.get("roots") or []
    for root in ([roots] if isinstance(roots, (str, Path)) else roots):
        out.extend(p for p in Path(root).rglob("*") if p.is_file())
    if cid_inputs.get("pattern_dir"):
        pattern_dir = Path(cid_inputs["pattern_dir"])
        if pattern_dir.is_dir():
            out.extend(p for p in pattern_dir.glob(cid_inputs.get("glob") or "*.txt")
                        if p.is_file())
    return out


def _artifact_record(path: Path) -> dict:
    path = Path(path)
    record = {"path": str(path), "exists": path.is_file()}
    if record["exists"]:
        record["bytes"] = path.stat().st_size
        record["sha256"] = sha256_file(path)
    return record


def _run_one(entry: dict, inputs: Mapping[str, Any], out_root: Path,
             index: Optional[DocumentIndex], incremental: bool) -> dict:
    """One category's unit of work. Never raises: an extractor blowing up is
    this category's FAILED result, not the fan-out's."""
    cid = entry["category_id"]
    started = time.perf_counter()
    result = {
        "category_id": cid,
        "checklist_item": entry.get("checklist_item"),
        "title": entry.get("title"),
        "extractor": entry.get("extractor"),
        "status": None,
        "reason": None,
        "artifacts": [],
        "source_documents": [],
        "detail": {},
        "thread_name": threading.current_thread().name,
    }

    if not entry.get("extractor"):
        result["status"] = STATUS_NO_EXTRACTOR
        result["reason"] = entry.get("no_extractor_reason")
        result["duration_seconds"] = round(time.perf_counter() - started, 6)
        return result

    cid_inputs = inputs.get(cid)
    if not cid_inputs:
        result["status"] = STATUS_INPUT_NOT_SUPPLIED
        result["reason"] = (f"no inputs supplied for category {cid!r}; expected keys "
                             f"{entry.get('input_keys') or []}")
        result["duration_seconds"] = round(time.perf_counter() - started, 6)
        return result

    out_dir = out_root / cid
    if incremental:
        declared = _declared_sources(entry, inputs)
        if declared and _sources_unchanged(index, declared) and any(out_dir.rglob("*")):
            result["status"] = STATUS_UP_TO_DATE
            result["reason"] = ("every declared source is already registered with a "
                                 "matching sha256 and this category's artifacts are on disk")
            result["artifacts"] = [_artifact_record(p) for p in sorted(out_dir.rglob("*"))
                                    if p.is_file()]
            result["source_documents"] = [{"path": str(p.resolve())} for p in declared]
            result["duration_seconds"] = round(time.perf_counter() - started, 6)
            return result

    out_dir.mkdir(parents=True, exist_ok=True)
    request = ExtractionRequest(category_id=cid, inputs=dict(cid_inputs), out_dir=out_dir)
    try:
        outcome = CATEGORY_EXTRACTORS[cid](request)
    except Exception as exc:  # noqa: BLE001 -- property 2: isolate, never abort the fan-out
        result["status"] = STATUS_FAILED
        result["reason"] = f"{type(exc).__name__}: {exc}"
        result["duration_seconds"] = round(time.perf_counter() - started, 6)
        return result

    result["status"] = STATUS_EXTRACTED
    result["artifacts"] = [_artifact_record(p) for p in outcome.artifacts]
    result["source_documents"] = _register_sources(index, cid, outcome.source_documents)
    result["detail"] = outcome.detail
    result["duration_seconds"] = round(time.perf_counter() - started, 6)
    return result


def dispatch_document_extractions(inputs: Mapping[str, Any], out_root,
                                  *, project_root=None,
                                  only: Optional[Sequence[str]] = None,
                                  max_workers: Optional[int] = None,
                                  incremental: bool = False,
                                  register: bool = True) -> dict:
    """Run every selected document category's extractor CONCURRENTLY and
    return one deterministic result set.

    Parallelism is safe here for a structural reason rather than a hopeful one,
    the same reasoning `subsystem_architecture_analysis.
    run_per_subsystem_analyses()` states for its own fan-out: each category
    reads its OWN declared inputs and writes into its OWN
    `<out_root>/<category_id>/` directory, checked distinct before any worker
    starts. The single shared mutable resource, the DocumentIndex, is written
    only through `_register_sources()` behind `_INDEX_LOCK`.

    Results are sorted back into declared category order, so a fan-out's output
    never depends on which worker happened to finish first.
    """
    assert_extractor_table_matches_categories()
    entries = _resolve_selection(only)
    out_root = Path(out_root)
    project_root = Path(project_root) if project_root else out_root

    out_dirs = {e["category_id"]: out_root / e["category_id"] for e in entries}
    if len(set(str(p.resolve()) for p in out_dirs.values())) != len(out_dirs):
        raise DocExtractionFanoutError(
            "two categories resolve to the same output directory; a concurrent "
            f"fan-out over {sorted(out_dirs)} would have them overwrite each other")
    out_root.mkdir(parents=True, exist_ok=True)

    index = DocumentIndex(Path(project_root)) if register else None

    order = {e["category_id"]: i for i, e in enumerate(entries)}
    workers = max_workers or min(8, len(entries)) or 1
    wall_started = time.perf_counter()
    if len(entries) == 1:
        results = [_run_one(entries[0], inputs, out_root, index, incremental)]
    else:
        with ThreadPoolExecutor(max_workers=workers,
                                 thread_name_prefix="doc-extract") as pool:
            results = list(pool.map(
                lambda e: _run_one(e, inputs, out_root, index, incremental),
                entries))
    wall = time.perf_counter() - wall_started
    results.sort(key=lambda r: order[r["category_id"]])

    counts = {status: 0 for status in EXTRACTION_STATUSES}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    worker_seconds = sum(r.get("duration_seconds") or 0.0 for r in results)

    return {
        "schema_version": SCHEMA_VERSION,
        "dispatched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "out_root": str(out_root.resolve()),
        "project_root": str(Path(project_root).resolve()),
        "categories_dispatched": [e["category_id"] for e in entries],
        "max_workers": workers,
        "incremental": incremental,
        "document_index_registered": register,
        # Evidence that this really fanned out rather than looped: the summed
        # per-worker time against the wall clock the whole batch took. It is a
        # measurement, never an assertion -- a batch in which only one category
        # had inputs is legitimately sequential and will say so.
        "wall_clock_seconds": round(wall, 6),
        "worker_seconds_sum": round(worker_seconds, 6),
        "distinct_worker_threads": len({r.get("thread_name") for r in results}),
        "counts": counts,
        "results": results,
    }


# ---------------------------------------------------------------------------
# CLI verb body -- shared by dv-harness doc-extract and `python -m`
# ---------------------------------------------------------------------------

def _load_inputs(path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise DocExtractionFanoutError(
            f"{path}: inputs file must be a JSON object keyed by category_id")
    unknown = [k for k in doc if k not in set(category_ids())]
    if unknown:
        raise DocExtractionFanoutError(
            f"{path}: unknown category keys {sorted(unknown)}; declared categories "
            f"are {list(category_ids())}")
    return doc


def execute_verb(args) -> int:
    """`dv-harness doc-extract <categories|plan|run>`. Returns the process exit
    code: 0 clean, 1 at least one category FAILED."""
    if args.dx_cmd == "categories":
        assert_extractor_table_matches_categories()
        payload = {"categories_version": json.loads(
                        CATEGORIES_PATH.read_text(encoding="utf-8"))["categories_version"],
                   "categories": [
                       {"category_id": c["category_id"],
                        "checklist_item": c.get("checklist_item"),
                        "title": c.get("title"),
                        "extractor": c.get("extractor"),
                        "no_extractor_reason": c.get("no_extractor_reason"),
                        "input_keys": c.get("input_keys") or []}
                       for c in load_categories()]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    inputs = _load_inputs(args.inputs) if args.inputs else {}
    if args.dx_cmd == "plan":
        print(json.dumps({"plan": plan_extractions(inputs, only=args.only)},
                          ensure_ascii=False, indent=2))
        return 0

    result = dispatch_document_extractions(
        inputs, args.out, project_root=args.project_root or args.out,
        only=args.only, max_workers=args.max_workers,
        incremental=args.incremental, register=not args.no_register)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["counts"].get(STATUS_FAILED) else 0


def _build_parser():
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.doc_extraction_fanout",
        description="Dispatch this repo's real document extractors concurrently across "
                     "self_check_list.md item #40's eleven document categories.")
    sub = ap.add_subparsers(dest="dx_cmd", required=True)
    sub.add_parser("categories", help="Print the eleven declared categories, each with the "
                                       "real extractor that handles it (or why none exists).")
    for name, helptext in (("plan", "Dry run: what a `run` WOULD dispatch. Opens no document."),
                            ("run", "Fan out every selected category concurrently.")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--inputs", help="JSON file keyed by category_id.")
        p.add_argument("--only", nargs="+", help="Restrict to these category ids.")
        if name == "run":
            p.add_argument("--out", required=True, help="Output root; each category writes "
                                                         "into <out>/<category_id>/.")
            p.add_argument("--project-root", help="Project root owning the DocumentIndex "
                                                   "(default: --out).")
            p.add_argument("--max-workers", type=int)
            p.add_argument("--incremental", action="store_true",
                            help="Skip a category whose declared sources are all already "
                                 "registered with a matching sha256 and whose artifacts "
                                 "are on disk.")
            p.add_argument("--no-register", action="store_true",
                            help="Do not record consumed sources in the DocumentIndex.")
    return ap


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return execute_verb(args)
    except DocExtractionFanoutError as exc:
        print(f"doc-extract {args.dx_cmd} FAILED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
