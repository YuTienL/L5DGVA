"""dv_harness/design_knowledge_output_package.py -- Design Knowledge Output
Package / downstream-consumer contract (2026-09-06).

THE GAP THIS CLOSES
--------------------
This repo grew a real "design knowledge" family, six modules answering six
different real questions about a project's own design evidence:

  * `design_source_inventory.py`      -- WHERE the design sources are, and
                                          how fresh/authoritative each is.
  * `design_knowledge_correlation.py` -- WHERE those sources AGREE, CONFLICT,
                                          or leave a GAP against each other.
  * `design_intent.py`                -- the DUT-controller-doc / user-guide
                                          distillation (intent.md /
                                          constraints.md) a scoreboard's
                                          ordering and exemptions consume.
  * `design_architecture_ir.py`       -- the real RTL module/port/instance
                                          tree plus a best-effort FSM scan.
  * `spec_intelligence.py`            -- the spec-extraction SCHEMA +
                                          validation/re-derivation gate.
  * `verification_intent_ir.py`       -- the semantic bridge from one
                                          requirement to what a generator
                                          should stimulate/check/cover.

Each already assembles its OWN real output, on its OWN input contract. Until
this module, nothing assembled them together: a caller who ran several of
these against one project had six separate JSON blobs with no single
exportable package, no bundle manifest, and -- the sharper gap -- no
DOCUMENTED statement of which of those six outputs' fields a downstream
generator (a vPlan writer, a scenario planner, a checker/coverage generator)
may simply TRUST versus which it must independently RE-VERIFY. A generator
that read `design_knowledge_correlation`'s `conflicts` list and picked a
winning value itself, or read `verification_intent_ir`'s `objective` text as
a verified fact instead of an interpretation, would silently reproduce
exactly the fabrication this project's Evidence Truth Rule exists to catch --
and nothing said, in one place, that either of those reads was wrong.
`grep -rn "downstream.consumer.contract|downstream_consumer_contract"
--include=*.py .` before this module matched nothing.

REUSE OVER REINVENT -- THIS MODULE WRITES NO SECOND BUNDLER, AND NO SECOND
IMPLEMENTATION OF ANY OF THE SIX MODULES ABOVE
---------------------------------------------------------------------------
Every one of the six per-slot outputs below is produced by calling that
module's OWN already-real, already-tested entry point directly:
`design_source_inventory.build_source_registry()`,
`design_knowledge_correlation.correlate()`,
`design_intent.validate_intent()`/`validate_constraints()`/
`render_intent_markdown()`/`render_constraints_markdown()`,
`design_architecture_ir.build_architecture_ir()`,
`spec_intelligence.analyze_spec_extraction()`,
`verification_intent_ir.build_verification_intent_ir_set()`. This module
never re-parses RTL, re-derives a conflict, re-validates a requirement, or
invents a value for any of them -- see `_LIVE_DISPATCH` and
`_resolve_design_intent()` below, each a thin call-and-catch wrapper.

The PACKAGING MECHANICS -- never a second, parallel bundler -- are the exact
ones `signoff_export.collect_signoff_bundle()` already established, the same
way `system_signoff_package.py` (the system-scope sibling of that same
bundle) already reused them: `signoff_export.compute_bundle_hash(manifest)`
(the real, independently-recomputable manifest-hash function) and
`signoff_export._artifact_content_digest()` (the same file-or-directory
content hasher). Every manifest entry this module writes has the IDENTICAL
four-key shape (`artifact`/`present`/`bundled_path`/`content_sha256`) both of
those already produce, so a reader parses this family's manifest.json exactly
the way it already parses a signoff or system-signoff one.

LIVE vs CALLER-SUPPLIED, one axis per slot, mirroring `system_signoff_package.
py`'s `subsystems`/`subsystem_contracts` split at slot granularity instead of
list granularity (each of the six slots is a SINGLE record, not a named list):
a slot's request is either `{"live": {<kwargs>}}` -- this module calls the
real producer itself and reports the real outcome, including a real
exception's text on failure, never letting one slot's failure crash the
package (the same per-artifact honesty `collect_signoff_bundle()` and
`system_signoff_package.py` already apply to every other candidate they
bundle) -- or `{"record": <precomputed output>}` -- a caller who already ran
that producer elsewhere hands in its real output directly, accepted
duck-typed exactly as `system_signoff_package.py`'s own `subsystem_contracts`
parameter already is. A slot given neither is `NOT_REQUESTED`, a fact kept
distinct from `NOT_AVAILABLE`/failed for the identical reason
`signoff_export.SIGNOFF_STATUS_NOT_RECORDED` is kept distinct from
`NOT_STARTED`: "nobody asked for this" and "this was asked for and came back
empty" are different facts about the run.

`design_intent` is the one slot shaped differently from the other five: its
real module produces UP TO TWO independent documents (an intent doc and a
constraints doc, each independently optional, each independently
schema-validated with citation basis required per condition -- see that
module's own docstring on why an uncited condition must not even validate).
This module reflects that directly: up to four sub-artifacts
(`design_intent:intent_doc`, `:intent_markdown`, `:constraints_doc`,
`:constraints_markdown`), each with its own manifest presence, rather than
forcing a false single present/absent boolean over two genuinely independent
documents.

WORST-WINS PACKAGE COMPLETENESS (CLAUDE.md's composite-gate rule, applied at
slot granularity, not at content-quality granularity)
---------------------------------------------------------------------------
`package_kind` is `PACKAGE_ASSEMBLY_COMPLETE` only when at least one slot was
requested AND every requested slot came back present with no error --
`PACKAGE_ASSEMBLY_PARTIAL` otherwise, a single missing/errored requested slot
dragging the WHOLE package down regardless of how many other slots are clean.
Zero slots requested is `PACKAGE_ASSEMBLY_PARTIAL`, not `COMPLETE` -- an empty
package proves nothing was assembled.

`package_kind` DELIBERATELY DOES NOT JUDGE THE DESIGN KNOWLEDGE ITSELF. A
package can be `PACKAGE_ASSEMBLY_COMPLETE` while its bundled
`design_knowledge_correlation.json` carries real CONFLICT findings, or its
`spec_intelligence.json` carries `status: FAIL` -- assembling a slot
successfully and that slot's OWN content being clean are two different
questions, the identical separation `signoff_export.collect_signoff_bundle()`
already keeps between a bundle's own `status: OK` and the project's actual
SIGNOFF-gate verdict. Conflating them here would be exactly the "complete-
looking bundle proves nothing about the real verdict" defect that module's
own GATE-AWARENESS history (see its docstring) already had to fix once.
`require_complete=True` refuses to write anything (not even an empty
`out_dir`) unless `package_kind` is `PACKAGE_ASSEMBLY_COMPLETE` -- the same
"refusal writes nothing" contract `collect_signoff_bundle(require_signoff_
pass=True)` and `collect_system_signoff_package(require_system_signoff_
pass=True)` already keep. Default `False`, for the identical reason both of
those default `False`: a package has to be PRODUCIBLE before anyone can look
at what is missing from it.

THE DOWNSTREAM-CONSUMER CONTRACT
---------------------------------
`DOWNSTREAM_CONSUMER_CONTRACT` (module-level, not per-run -- it documents the
FAMILY's own real epistemic shape, established once in each member module's
own docstring and re-stated here as one indexed reference) names, per slot,
what a generator MAY RELY ON versus what it MUST RE-VERIFY. It is not
invented here: every line traces to a real, already-written boundary
statement in the owning module --
`design_knowledge_correlation.py`'s own "no arbitration" boundary (the same
ARBITRATION boundary `requirement_contract.py` keeps for its own conflict
findings), `verification_intent_ir.py`'s own `evidence_provenance.
AGENT_SELF_ATTESTED` self-attestation of every interpretive field versus the
verbatim-preserved real per-domain evidence, `design_architecture_ir.py`'s
own "best-effort FSM scan, never a verified model" framing,
`design_intent.py`'s own citation-required transcription boundary,
`spec_intelligence.py`'s own evidence-provenance caveat, and
`design_source_inventory.py`'s own freshness-is-as-of-`last_checked`
framing. `assert_contract_covers_family()` runs at import, holding
`FAMILY_SLOTS` and the contract's own key set equal in both directions --
the identical "can never silently drift" discipline `signoff_export.
assert_baseline_covers_section_238()` already keeps for its own fixed field
list. The contract is bundled into every package as its own manifest
artifact (`downstream_consumer_contract.json`) -- a human or a generator
reading an exported package does not have to go read six module docstrings
to find it.

WHAT THIS MODULE IS NOT
-------------------------
It decides no arbitration, authors no design intent, extracts no requirement,
parses no RTL itself, and runs no simulation/build/regression/LSF submission.
No governance state is written beyond the package directory itself; there is
deliberately no `STAGE_GATES` entry (an assembled-but-conflict-laden package
is neither a pass nor a fail of anything). Per this task's own file-safety
scope (`cli.py`/`gates.py` are large, heavily-edited files this task must not
touch), there is no `dv-harness` CLI verb -- the front door is
`python -m dv_harness.design_knowledge_output_package collect ...`, the same
disclosed choice `system_signoff_package.py` and several other recent
sibling modules already make.

DISCLOSED RESIDUAL. `verification_intent_ir`'s `power_intent_report` kwarg
(a `PowerIntentReport` object, not a JSON-serializable shape) is not wired
into this module's `live` dispatch for that slot -- only `source_paths`/
`sys_regmap_doc`/`upf_paths` are. A caller who has already run
`power_intent.analyze_power_intent()` and wants its result reflected can
still get it into the package: build the full `VerificationIntentIR` set
itself and hand the result in as `{"record": [...]}` on that slot, the same
CALLER_SUPPLIED path every other slot already supports.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import design_architecture_ir as dair
from . import design_intent as di
from . import design_knowledge_correlation as dkc
from . import design_source_inventory as dsi
from . import signoff_export as se
from . import spec_intelligence as si
from . import verification_intent_ir as vir

SCHEMA_VERSION = "1.0"

# The six real family members this module assembles. Order is the same one
# the module docstring introduces them in.
FAMILY_SLOTS: Tuple[str, ...] = (
    "design_source_inventory",
    "design_knowledge_correlation",
    "design_intent",
    "design_architecture_ir",
    "spec_intelligence",
    "verification_intent_ir",
)

#: Per-slot provenance -- mirrors system_signoff_package.py's
#: SOURCE_LIVE_ASSEMBLED / SOURCE_CALLER_SUPPLIED naming.
SOURCE_LIVE_ASSEMBLED = "LIVE_ASSEMBLED"
SOURCE_CALLER_SUPPLIED = "CALLER_SUPPLIED"
SOURCE_NOT_REQUESTED = "NOT_REQUESTED"
SOURCE_INVALID_REQUEST = "INVALID_REQUEST"

PACKAGE_ASSEMBLY_COMPLETE = "PACKAGE_ASSEMBLY_COMPLETE"
PACKAGE_ASSEMBLY_PARTIAL = "PACKAGE_ASSEMBLY_PARTIAL"
PACKAGE_KINDS: Tuple[str, ...] = (PACKAGE_ASSEMBLY_COMPLETE, PACKAGE_ASSEMBLY_PARTIAL)


class DesignKnowledgeOutputPackageError(Exception):
    """A real caller-usage error (CLI/config shape), never a silently-
    repaired input."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Per-slot live dispatch -- one thin call into each real module's own real
# entry point. None of these re-derive anything the owning module already
# computes.
# ---------------------------------------------------------------------------

def _live_design_source_inventory(kw: Mapping[str, Any]) -> dict:
    return dsi.build_source_registry(kw.get("entries") or [])


def _live_design_knowledge_correlation(kw: Mapping[str, Any]) -> dict:
    return dkc.correlate(kw.get("sources"), kw.get("expected_facts"))


def _live_design_architecture_ir(kw: Mapping[str, Any]) -> dict:
    return dair.build_architecture_ir(
        kw.get("rtl_files") or [],
        verible_bin=kw.get("verible_bin", dair.DEFAULT_VERIBLE_BIN),
        top_module=kw.get("top_module"),
        max_instance_depth=kw.get("max_instance_depth", 64),
    )


def _live_spec_intelligence(kw: Mapping[str, Any]) -> dict:
    return si.analyze_spec_extraction(kw.get("document"), project_root=kw.get("project_root"))


def _live_verification_intent_ir(kw: Mapping[str, Any]) -> List[dict]:
    irs = vir.build_verification_intent_ir_set(
        kw.get("records") or [],
        source_paths=kw.get("source_paths"),
        sys_regmap_doc=kw.get("sys_regmap_doc"),
        upf_paths=kw.get("upf_paths"),
    )
    return [one.to_dict() for one in irs]


_LIVE_DISPATCH: Dict[str, Callable[[Mapping[str, Any]], Any]] = {
    "design_source_inventory": _live_design_source_inventory,
    "design_knowledge_correlation": _live_design_knowledge_correlation,
    "design_architecture_ir": _live_design_architecture_ir,
    "spec_intelligence": _live_spec_intelligence,
    "verification_intent_ir": _live_verification_intent_ir,
}


def _resolve_single_record_slot(
    name: str, spec: Optional[Mapping[str, Any]], live_fn: Callable[[Mapping[str, Any]], Any],
) -> Tuple[Optional[Any], str, Optional[str]]:
    """(record_or_None, source, error_or_None) for one of the five slots
    whose real output is a single record. Never lets a live call's exception
    escape -- the same per-artifact honesty `system_signoff_package.py`'s
    own `_assemble_one_subsystem()` already applies."""
    if spec is None:
        return None, SOURCE_NOT_REQUESTED, None
    if not isinstance(spec, Mapping):
        return None, SOURCE_INVALID_REQUEST, (
            f"{name}: slot input must be a mapping with 'record' or 'live', "
            f"got {type(spec).__name__}")
    has_record = "record" in spec
    has_live = "live" in spec
    if has_record and has_live:
        return None, SOURCE_INVALID_REQUEST, f"{name}: supply exactly one of 'record' or 'live', not both"
    if has_record:
        return spec["record"], SOURCE_CALLER_SUPPLIED, None
    if has_live:
        live_kwargs = spec["live"] if isinstance(spec["live"], Mapping) else {}
        try:
            return live_fn(live_kwargs), SOURCE_LIVE_ASSEMBLED, None
        except Exception as exc:  # pragma: no cover - exercised via real malformed input in tests
            return None, SOURCE_LIVE_ASSEMBLED, f"{type(exc).__name__}: {exc}"
    return None, SOURCE_INVALID_REQUEST, f"{name}: mapping must carry 'record' or 'live'"


def _resolve_design_intent(
    spec: Optional[Mapping[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """design_intent's own resolver: up to two independent documents
    (intent / constraints), each validated and rendered through the real
    `design_intent.py` functions on the live path. Returns
    (outputs_or_None, source, error_or_None); `outputs` may carry any subset
    of `intent_doc`/`intent_markdown`/`constraints_doc`/`constraints_markdown`
    -- a partial success (e.g. intent validates, constraints does not) is
    reported as `outputs` carrying the intent half AND a real error naming
    the constraints half, never silently dropping either fact."""
    if spec is None:
        return None, SOURCE_NOT_REQUESTED, None
    if not isinstance(spec, Mapping):
        return None, SOURCE_INVALID_REQUEST, (
            f"design_intent: slot input must be a mapping with 'record' or 'live', "
            f"got {type(spec).__name__}")
    has_record = "record" in spec
    has_live = "live" in spec
    if has_record and has_live:
        return None, SOURCE_INVALID_REQUEST, "design_intent: supply exactly one of 'record' or 'live'"
    if has_record:
        record = spec["record"]
        if not isinstance(record, Mapping):
            return None, SOURCE_INVALID_REQUEST, "design_intent record must be a mapping"
        return dict(record), SOURCE_CALLER_SUPPLIED, None
    if not has_live:
        return None, SOURCE_INVALID_REQUEST, "design_intent: mapping must carry 'record' or 'live'"

    live = spec["live"] if isinstance(spec["live"], Mapping) else {}
    outputs: Dict[str, Any] = {}
    errors: List[str] = []

    intent_doc = live.get("intent_doc")
    if intent_doc is not None:
        try:
            di.validate_intent(intent_doc)
            outputs["intent_doc"] = intent_doc
            outputs["intent_markdown"] = di.render_intent_markdown(intent_doc)
        except Exception as exc:
            errors.append(f"intent: {type(exc).__name__}: {exc}")

    constraints_doc = live.get("constraints_doc")
    if constraints_doc is not None:
        try:
            di.validate_constraints(constraints_doc)
            outputs["constraints_doc"] = constraints_doc
            outputs["constraints_markdown"] = di.render_constraints_markdown(constraints_doc)
        except Exception as exc:
            errors.append(f"constraints: {type(exc).__name__}: {exc}")

    if not outputs and not errors:
        return None, SOURCE_LIVE_ASSEMBLED, (
            "design_intent live: neither intent_doc nor constraints_doc was supplied")
    return (outputs or None), SOURCE_LIVE_ASSEMBLED, ("; ".join(errors) if errors else None)


# ---------------------------------------------------------------------------
# The documented downstream-consumer contract (module-level -- see docstring)
# ---------------------------------------------------------------------------

DOWNSTREAM_CONSUMER_CONTRACT: Dict[str, Dict[str, Any]] = {
    "design_source_inventory": {
        "producer": "dv_harness.design_source_inventory.build_source_registry()",
        "may_rely_on": [
            "`hash` is a real sha256 this run computed by reading the file/tree "
            "at `path` -- a generator may trust it as a real content "
            "fingerprint of the source AT THE MOMENT this package was "
            "assembled.",
            "`authority` is resolved through `source_authority.authority_source()`, "
            "this project's one authority-tier ranking, never re-derived here -- "
            "a generator may trust `authority.rank` as that same real ranking.",
        ],
        "must_reverify": [
            "`status` (CURRENT/STALE/SUPERSEDED/UNKNOWN/NOT_AVAILABLE) and "
            "`last_checked` describe freshness ONLY as of export time; a "
            "generator consuming this package after the source files may have "
            "changed again must re-run design_source_inventory (or recompute "
            "the hash) rather than trust an exported CURRENT as still true.",
            "an authority of `NOT_APPLICABLE` with reason "
            "`UNRESOLVED_AUTHORITY_HINT` means this source sits OUTSIDE the "
            "conflict-resolution axis entirely -- a generator must not treat "
            "it as a real but merely low-ranked tier.",
        ],
    },
    "design_knowledge_correlation": {
        "producer": "dv_harness.design_knowledge_correlation.correlate()",
        "may_rely_on": [
            "every `CONFLICT`/`GAP`/`DOCUMENTED_VS_IMPLEMENTED_*` finding lists "
            "every citing source and its asserted value verbatim -- a generator "
            "may trust the finding's EXISTENCE and its full participant list.",
        ],
        "must_reverify": [
            "this module performs NO ARBITRATION (its own documented boundary, "
            "the same ARBITRATION boundary requirement_contract.py keeps for "
            "its own conflict findings): a `CONFLICT` finding never says which "
            "value is right. A generator MUST NOT auto-pick a value out of a "
            "conflict's value groups; it must escalate to a human, or to "
            "`source_authority.resolve_conflict()` given each side's own "
            "authority tier.",
            "a `GAP` finding is only as complete as the caller-declared "
            "`expected_facts` list fed into THIS run; an empty `gaps` list "
            "does not mean nothing is missing, only that nothing on that "
            "declared expectation list was found missing.",
        ],
    },
    "design_intent": {
        "producer": "dv_harness.design_intent (validate_intent/validate_constraints/"
                    "render_intent_markdown/render_constraints_markdown)",
        "may_rely_on": [
            "every legal-drop/backpressure/ordering condition that validated "
            "against the schema carries a `basis` (`document`+`section`) "
            "citation -- schema validation refuses an uncited condition, so a "
            "generator may trust that a citation exists (though not, without "
            "re-checking, that the citation is an ACCURATE reading of that "
            "section -- see below).",
        ],
        "must_reverify": [
            "this module TRANSCRIBES and VALIDATES structure; it never "
            "authors intent (its own docstring). A generator must not treat a "
            "legal-drop/backpressure condition as license to suppress a "
            "scoreboard mismatch without being able to trace that condition's "
            "`basis` back to the cited document+section -- the citation proves "
            "a source was named, not that the transcription is faithful to it.",
        ],
    },
    "design_architecture_ir": {
        "producer": "dv_harness.design_architecture_ir.build_architecture_ir()",
        "may_rely_on": [
            "a module whose per-file `status` is `PARSED` has ports/parameters/"
            "signals/instances/continuous_assigns byte-identical to "
            "verible_parser.py's own real parse -- nothing here re-derives "
            "that structure.",
        ],
        "must_reverify": [
            "`fsm_extraction.candidates` is a BEST-EFFORT textual scan "
            "(extract_fsm_candidates()), never a verified FSM model -- a "
            "generator must treat it as a hint to confirm against the real "
            "RTL, never as a proven state machine.",
            "a per-file `status` of `NOT_AVAILABLE`/`PARSE_ERROR` means that "
            "file's structure is UNKNOWN, not empty -- a generator must not "
            "read an empty `modules` list for such a file as 'this file "
            "declares no modules'.",
        ],
    },
    "spec_intelligence": {
        "producer": "dv_harness.spec_intelligence.analyze_spec_extraction()",
        "may_rely_on": [
            "a `PASS` status means every extracted atomic requirement passed "
            "schema + status re-derivation and the REFINES/EXTENDS dependency "
            "graph is acyclic -- a generator may walk `dependency_graph`'s "
            "topological order as safe.",
        ],
        "must_reverify": [
            "`evidence_provenance_caveat` (from evidence_provenance.py) must "
            "be carried forward by any generator that quotes a requirement's "
            "text -- an AGENT_SELF_ATTESTED extraction is not independently "
            "verified evidence, only a validated SHAPE.",
            "a `NOT_AVAILABLE` status means nothing to analyze, not 'nothing "
            "wrong' -- it must not be read as a PASS.",
        ],
    },
    "verification_intent_ir": {
        "producer": "dv_harness.verification_intent_ir.build_verification_intent_ir_set()",
        "may_rely_on": [
            "any per-domain sub-plan whose DUT evidence comes from a real "
            "producer (power_intent.py / interrupt_dma_clock_reset_extraction.py "
            "/ sys_regmap.py / protocol_capability.py) carries that producer's "
            "OWN real status/PASS-FAIL vocabulary verbatim -- a generator may "
            "trust that status exactly as it would trust calling that producer "
            "directly.",
        ],
        "must_reverify": [
            "EVERY record's own `objective`/`stimulus_intent`/`checker_intent`/"
            "`coverage_intent` and domain narrative is "
            "`evidence_provenance.AGENT_SELF_ATTESTED` -- an INTERPRETATION of "
            "the requirement, never a verified fact (this module's own "
            "docstring: 'never a generated test, never a verified fact'). A "
            "generator must carry `evidence_provenance_caveat` forward into "
            "anything it emits from this IR.",
            "the `error_recovery` and `performance` domains have NO real "
            "evidence producer anywhere in this harness -- a generator must "
            "treat those two domains' plans as fully un-grounded regardless of "
            "what narrative text they contain.",
        ],
    },
}

#: A cross-cutting note that applies to the PACKAGE as a whole rather than to
#: one slot -- kept out of FAMILY_SLOTS' own per-slot contract entries (and
#: out of assert_contract_covers_family()'s coverage check) since it is not a
#: sixth family member.
DOWNSTREAM_CONSUMER_CONTRACT_PACKAGE_LEVEL_NOTE = (
    "`bundle_hash` (reused verbatim from signoff_export.compute_bundle_hash()) "
    "attests only to ARTIFACT PRESENCE and PATH within this export -- exactly "
    "as it does in signoff_export.py's own bundle, per that module's own "
    "documented limitation. A generator wanting to detect a bundled artifact's "
    "CONTENT being replaced after export must check that artifact's own "
    "`content_sha256` in manifest.json, not `bundle_hash` alone."
)


def assert_contract_covers_family() -> None:
    """Both directions: a family slot with no contract entry would be
    silently undocumented, and a contract entry for a name that is not a real
    family slot would claim coverage of something that does not exist. Runs
    at import, the identical discipline `signoff_export.
    assert_baseline_covers_section_238()` already keeps for its own fixed
    field list."""
    declared = set(FAMILY_SLOTS)
    documented = set(DOWNSTREAM_CONSUMER_CONTRACT)
    missing = sorted(declared - documented)
    extra = sorted(documented - declared)
    if missing or extra:
        raise AssertionError(
            f"design knowledge downstream-consumer contract drifted from "
            f"FAMILY_SLOTS: no contract entry for {missing}; contract entry "
            f"for undeclared slot {extra}")
    for name, entry in DOWNSTREAM_CONSUMER_CONTRACT.items():
        if not entry.get("may_rely_on") or not entry.get("must_reverify"):
            raise AssertionError(
                f"design knowledge downstream-consumer contract entry {name!r} "
                f"must declare a non-empty 'may_rely_on' AND 'must_reverify' "
                f"list -- a slot with nothing a generator must re-verify is "
                f"exactly the overclaim this contract exists to prevent")


assert_contract_covers_family()


# ---------------------------------------------------------------------------
# Bundle mechanics -- reused verbatim from signoff_export.py, never
# reimplemented (see module docstring).
# ---------------------------------------------------------------------------

def _record_manifest_entry(manifest: List[Dict[str, Any]], out_dir: Path,
                            artifact: str, present: bool,
                            bundled_rel: Optional[Path]) -> None:
    content = None
    if present and bundled_rel is not None:
        content = se._artifact_content_digest(out_dir / bundled_rel)
    manifest.append({
        "artifact": artifact,
        "present": present,
        "bundled_path": bundled_rel.as_posix() if bundled_rel is not None else None,
        "content_sha256": content,
    })


def _write_json(out_dir: Path, rel: Path, doc: Any) -> None:
    path = out_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_text(out_dir: Path, rel: Path, text: str) -> None:
    path = out_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# The one entry point
# ---------------------------------------------------------------------------

_DESIGN_INTENT_SUB_ARTIFACTS: Tuple[Tuple[str, str, bool], ...] = (
    ("intent_doc", "design_intent/intent.json", False),
    ("intent_markdown", "design_intent/intent.md", True),
    ("constraints_doc", "design_intent/constraints.json", False),
    ("constraints_markdown", "design_intent/constraints.md", True),
)


def collect_design_knowledge_package(
        root, out_dir, *,
        design_source_inventory: Optional[Mapping[str, Any]] = None,
        design_knowledge_correlation: Optional[Mapping[str, Any]] = None,
        design_intent: Optional[Mapping[str, Any]] = None,
        design_architecture_ir: Optional[Mapping[str, Any]] = None,
        spec_intelligence: Optional[Mapping[str, Any]] = None,
        verification_intent_ir: Optional[Mapping[str, Any]] = None,
        require_complete: bool = False,
) -> Dict[str, Any]:
    """Assemble the design-knowledge family's real outputs under `out_dir`.

    Each of the six keyword slots is optional and, when given, is either
    `{"record": <precomputed output>}` (a caller who already ran that
    producer hands in its real output directly) or `{"live": {<kwargs>}}`
    (this function calls the real producer itself with those kwargs). A slot
    left `None` is `NOT_REQUESTED` -- not counted against completeness.

    Everything is resolved and `package_kind` decided BEFORE anything is
    written, so `require_complete=True` can refuse (write nothing at all, not
    even an empty `out_dir`) exactly like `signoff_export.
    collect_signoff_bundle(require_signoff_pass=True)` already does.
    """
    root = Path(root).resolve()
    out_dir = Path(out_dir).resolve()

    resolved: Dict[str, Tuple[Optional[Any], str, Optional[str]]] = {}
    for name, spec in (
        ("design_source_inventory", design_source_inventory),
        ("design_knowledge_correlation", design_knowledge_correlation),
        ("design_architecture_ir", design_architecture_ir),
        ("spec_intelligence", spec_intelligence),
        ("verification_intent_ir", verification_intent_ir),
    ):
        resolved[name] = _resolve_single_record_slot(name, spec, _LIVE_DISPATCH[name])
    resolved["design_intent"] = _resolve_design_intent(design_intent)

    slot_status: Dict[str, Dict[str, Any]] = {}
    for name in FAMILY_SLOTS:
        record, source, error = resolved[name]
        slot_status[name] = {
            "requested": source not in (SOURCE_NOT_REQUESTED,),
            "source": source,
            "present": record is not None,
            "error": error,
        }

    requested = [n for n in FAMILY_SLOTS if slot_status[n]["requested"]]
    complete = bool(requested) and all(
        slot_status[n]["present"] and slot_status[n]["error"] is None for n in requested)
    package_kind = PACKAGE_ASSEMBLY_COMPLETE if complete else PACKAGE_ASSEMBLY_PARTIAL

    if require_complete and package_kind != PACKAGE_ASSEMBLY_COMPLETE:
        return {
            "status": "REFUSED",
            "reason": "PACKAGE_NOT_COMPLETE",
            "detail": (
                f"package_kind would be {package_kind!r}, not "
                f"{PACKAGE_ASSEMBLY_COMPLETE!r}: at least one requested family "
                f"slot is missing or errored (see slot_status) -- no complete "
                f"design-knowledge package can be produced for this input."
            ),
            "out_dir": str(out_dir),
            "package_kind": package_kind,
            "slot_status": slot_status,
            "manifest": [],
            "bundle_hash": None,
            "bundled_count": 0,
            "missing_count": 0,
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: List[Dict[str, Any]] = []

    for name in ("design_source_inventory", "design_knowledge_correlation",
                 "design_architecture_ir", "spec_intelligence", "verification_intent_ir"):
        record, _source, _error = resolved[name]
        rel = Path(f"{name}.json")
        if record is not None:
            _write_json(out_dir, rel, record)
            _record_manifest_entry(manifest, out_dir, name, True, rel)
        else:
            _record_manifest_entry(manifest, out_dir, name, False, None)

    di_outputs = resolved["design_intent"][0] or {}
    for key, rel_name, is_markdown in _DESIGN_INTENT_SUB_ARTIFACTS:
        value = di_outputs.get(key)
        artifact = f"design_intent:{key}"
        rel = Path(rel_name)
        if value is not None:
            if is_markdown:
                _write_text(out_dir, rel, value)
            else:
                _write_json(out_dir, rel, value)
            _record_manifest_entry(manifest, out_dir, artifact, True, rel)
        else:
            _record_manifest_entry(manifest, out_dir, artifact, False, None)

    # The documented downstream-consumer contract -- a property of the
    # FAMILY, not of this particular run's data, so it is always bundled.
    contract_rel = Path("downstream_consumer_contract.json")
    contract_doc = {
        "schema_version": SCHEMA_VERSION,
        "slots": DOWNSTREAM_CONSUMER_CONTRACT,
        "package_level_note": DOWNSTREAM_CONSUMER_CONTRACT_PACKAGE_LEVEL_NOTE,
    }
    _write_json(out_dir, contract_rel, contract_doc)
    _record_manifest_entry(manifest, out_dir, "downstream_consumer_contract", True, contract_rel)

    # The one function this whole module exists to REUSE rather than
    # reimplement -- see module docstring.
    bundle_hash = se.compute_bundle_hash(manifest)

    manifest_doc = {
        "schema_version": SCHEMA_VERSION,
        "assembled_at": _now_iso(),
        "root": str(root),
        "package_kind": package_kind,
        "slot_status": slot_status,
        "manifest": manifest,
        "bundle_hash": bundle_hash,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    bundled_count = sum(1 for m in manifest if m["present"])
    missing_count = sum(1 for m in manifest if not m["present"])

    return {
        "status": "OK",
        "out_dir": str(out_dir),
        "package_kind": package_kind,
        "slot_status": slot_status,
        "manifest": manifest,
        "bundle_hash": bundle_hash,
        "bundled_count": bundled_count,
        "missing_count": missing_count,
        "downstream_consumer_contract": DOWNSTREAM_CONSUMER_CONTRACT,
    }


# ---------------------------------------------------------------------------
# Rendering + CLI front door
# ---------------------------------------------------------------------------

def render_package_text(result: Dict[str, Any]) -> str:
    lines = [
        f"DESIGN KNOWLEDGE OUTPUT PACKAGE: {result['status']}"
        + (f"  package_kind={result.get('package_kind')}" if result.get("package_kind") else ""),
    ]
    if result["status"] == "REFUSED":
        lines.append(f"  reason: {result.get('reason')}")
        lines.append(f"  detail: {result.get('detail')}")
        return "\n".join(lines)
    lines.append(f"  out_dir: {result['out_dir']}")
    lines.append(f"  bundle_hash: {result['bundle_hash']}")
    lines.append(f"  bundled={result['bundled_count']}  missing={result['missing_count']}")
    lines.append("  slots:")
    for name in FAMILY_SLOTS:
        st = result["slot_status"][name]
        lines.append(
            f"    - {name}: requested={st['requested']} source={st['source']} "
            f"present={st['present']}" + (f"  ERROR={st['error']}" if st.get("error") else ""))
    return "\n".join(lines)


def _load_json_required(path: str, what: str) -> Any:
    p = Path(path)
    if not p.is_file():
        raise DesignKnowledgeOutputPackageError(f"{what}: not a real file: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DesignKnowledgeOutputPackageError(f"{what}: {p} is not valid JSON: {exc}") from exc


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.design_knowledge_output_package collect --root
    <dir> --out-dir <dir> --config <config.json> [--require-complete] [--json]`

    `--config` is a JSON object; each of the six FAMILY_SLOTS keys is
    optional and, when present, shaped `{"record": <output>}` or
    `{"live": {<kwargs for that module's real function>}}` -- see the module
    docstring's `collect_design_knowledge_package()` for the exact kwargs
    each live slot accepts.

    Exit 0 PACKAGE_ASSEMBLY_COMPLETE, 1 PACKAGE_ASSEMBLY_PARTIAL, 2 REFUSED
    or a usage error. No `dv-harness` CLI verb was added -- `cli.py`/
    `gates.py` are out of this task's own file-safety scope."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="design-knowledge-output-package",
        description="Assemble the design-knowledge family's real outputs "
                    "(design_source_inventory / design_knowledge_correlation / "
                    "design_intent / design_architecture_ir / spec_intelligence / "
                    "verification_intent_ir) into one exportable package with a "
                    "documented downstream-consumer contract, reusing "
                    "signoff_export.py's bundle-manifest mechanics.")
    ap.add_argument("verb", choices=["collect"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--out-dir", required=True, dest="out_dir")
    ap.add_argument("--config", required=True, dest="config_path")
    ap.add_argument("--require-complete", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    try:
        config = _load_json_required(args.config_path, "--config")
        if not isinstance(config, Mapping):
            raise DesignKnowledgeOutputPackageError(
                f"--config {args.config_path} must contain a JSON object")
        unknown = sorted(set(config) - set(FAMILY_SLOTS))
        if unknown:
            raise DesignKnowledgeOutputPackageError(
                f"--config names unrecognized slot(s) {unknown}; must be a subset of {list(FAMILY_SLOTS)}")

        result = collect_design_knowledge_package(
            args.root, args.out_dir,
            design_source_inventory=config.get("design_source_inventory"),
            design_knowledge_correlation=config.get("design_knowledge_correlation"),
            design_intent=config.get("design_intent"),
            design_architecture_ir=config.get("design_architecture_ir"),
            spec_intelligence=config.get("spec_intelligence"),
            verification_intent_ir=config.get("verification_intent_ir"),
            require_complete=args.require_complete)
    except DesignKnowledgeOutputPackageError as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str) if args.json
          else render_package_text(result))

    if result["status"] == "REFUSED":
        return 2
    return 0 if result["package_kind"] == PACKAGE_ASSEMBLY_COMPLETE else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys
    return execute_verb(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    import sys
    sys.exit(main())
