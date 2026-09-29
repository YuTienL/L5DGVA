"""dv_harness/uvm_generator/address_map_verifier.py -- real encoding of
CORE/ip-uvm-dv-gen/SKILL.md's "Finding the address map when no document is
trustworthy" method (originating in D:/DV/Task/USB/.claude/agents/
IP_UVM_DV_Gen.md's Step 3): require THREE INDEPENDENT SOURCES to agree
before a generator commits a register base address --

  1. The decoder itself (the address comparator, cited file:line) -- primary,
     mandatory.
  2. The existing BFM patterns' access histogram (accesses counted per base
     across all patterns) -- corroborates that the decoder's claimed base is
     actually a live, exercised block, not a plausible-looking guess.
  3. A register document, read LAST, as corroboration only -- it never
     decides, and a document disagreement does not block committal (a
     register doc listing two instances at the same address is not
     necessarily a typo per SKILL.md; a shared-select/broadcast-address
     decoder idiom can make that legitimate).

GAP CLOSED (2026-08-29, gap-comparison prioritized-gap #1): this method was
previously absent from v50 at BOTH the code and the SKILL.md doc level --
the single highest-value fact-establishment technique in IP_UVM_DV_Gen.md
had no trace anywhere in dv_harness/. This module makes it a real,
schema-expressible generator capability: `verify_address_map` refuses to
produce a verified base address from decoder evidence alone (source 1) or
from decoder+doc without histogram corroboration (source 1+3, skipping the
mandatory source 2) -- it raises a typed error in both cases rather than
silently trusting a single source. Only source 1+2 agreement (with source 3
recorded as AGREES/DISAGREES/NOT_AVAILABLE, but never gating) yields a
VERIFIED entry that `emit_verified_base_addr_defines` will emit a
`` `define `` for.

Same typed-error convention as this package's other generators
(amba_fabric_generator.AddressMapError, bind_mechanism_generator.
BindTopologyError, generator.py's Missing*EvidenceError family): a short
SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict -- never a
silently-guessed or silently-downgraded address.
"""
from __future__ import annotations

from .amba_fabric_generator import parse_addr


class AddressMapVerificationError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _normalize_base(raw, *, context: str):
    try:
        return parse_addr(raw)
    except (TypeError, ValueError) as exc:
        raise AddressMapVerificationError("UNPARSEABLE_BASE_ADDRESS", {
            "context": context, "raw_value": raw, "parse_error": str(exc),
        }) from exc


def _index_histogram(bfm_access_histogram):
    """`bfm_access_histogram` is a list of {"base", "access_count", "source"}
    dicts -- one entry per base actually observed while counting accesses
    across the BFM patterns (SKILL.md source 2). `source` is a mandatory
    citation of which pattern(s) were counted (e.g. "command.txt,
    sanity/ep0_init.txt"), same evidence discipline as every other generator
    in this package -- a histogram count with no stated source is exactly the
    kind of silently-asserted fact the Evidence Truth Rule forbids."""
    index = {}
    for i, entry in enumerate(bfm_access_histogram or []):
        if "base" not in entry:
            raise AddressMapVerificationError("MISSING_HISTOGRAM_EVIDENCE", {
                "index": i, "field": "base",
            })
        if not entry.get("source"):
            raise AddressMapVerificationError("MISSING_HISTOGRAM_EVIDENCE", {
                "index": i, "field": "source", "base": entry.get("base"),
            })
        count = entry.get("access_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise AddressMapVerificationError("MISSING_HISTOGRAM_EVIDENCE", {
                "index": i, "field": "access_count", "base": entry.get("base"),
                "got": count,
            })
        base = _normalize_base(entry["base"], context=f"bfm_access_histogram[{i}]")
        index[base] = {"access_count": count, "source": entry["source"]}
    return index


def _index_register_doc(register_doc_entries):
    """`register_doc_entries` is optional -- a target with "no specification
    available" is a real, expected state (same as the vPlan's own
    `spec section` rule: say so, don't guess). Each supplied entry still
    needs its own citation (`doc_ref`) once it opts in, though -- corroborating
    evidence is still evidence."""
    index = {}
    for i, entry in enumerate(register_doc_entries or []):
        instance = entry.get("instance")
        if not instance:
            raise AddressMapVerificationError("MISSING_DOC_EVIDENCE", {
                "index": i, "field": "instance",
            })
        if "base" not in entry:
            raise AddressMapVerificationError("MISSING_DOC_EVIDENCE", {
                "index": i, "instance": instance, "field": "base",
            })
        if not entry.get("doc_ref"):
            raise AddressMapVerificationError("MISSING_DOC_EVIDENCE", {
                "index": i, "instance": instance, "field": "doc_ref",
            })
        index[instance] = {
            "base": _normalize_base(entry["base"], context=f"register_doc_entries[{i}]"),
            "doc_ref": entry["doc_ref"],
        }
    return index


#: Which authority level a `register_doc_entries` entry occupies in
#: `dv_harness.source_authority.AUTHORITY_ORDER`. Tier 6 ("controller
#: doc/programming guide") rather than tier 4 ("register file"), because this
#: module's own contract calls it "a register document, read LAST, as
#: corroboration only" -- a human-written programming document, not a
#: machine-readable register description. The choice is disclosed rather than
#: buried because it is a judgment: what it CANNOT change is the outcome, since
#: the decoder is tier 3 ("DUT RTL") and outranks both candidates. Override via
#: `escalate_doc_disagreements(..., doc_source=...)` for a project whose
#: register_doc_entries really are a register file.
DOC_AUTHORITY_SOURCE = "controller_doc"
DECODER_AUTHORITY_SOURCE = "dut_rtl"


def doc_disagreement_conflict(entry, *, doc_source: str = DOC_AUTHORITY_SOURCE):
    """One DISAGREES entry from `verify_address_map` -> a `source_authority`
    conflict between the decoder (tier 3) and the register document (tier 6).

    Always RESOLVED in the decoder's favor -- which is exactly this module's
    long-standing "the document corroborates, it never decides" rule, now
    stated as the general authority order rather than as a rule local to this
    file. Raises if handed an entry that does not actually disagree: a
    conflict record for two sources that agree would be a fabricated one.
    """
    from ..source_authority import SourceClaim, resolve_conflict

    if entry.get("doc_status") != "DISAGREES":
        raise AddressMapVerificationError("NOT_A_DOC_DISAGREEMENT", {
            "instance": entry.get("instance"), "doc_status": entry.get("doc_status"),
        })
    return resolve_conflict([
        SourceClaim(source=DECODER_AUTHORITY_SOURCE,
                    claim=f"{entry['instance']} base = {entry['base_hex']}",
                    evidence_path=entry["decoder_evidence"]),
        SourceClaim(source=doc_source,
                    claim=f"{entry['instance']} base disagrees with the decoder-verified value",
                    evidence_path=entry["doc_ref"]),
    ])


def escalate_doc_disagreements(verified_entries, question_store, *,
                               doc_source: str = DOC_AUTHORITY_SOURCE, now=None):
    """File every DISAGREES entry into the REAL question queue and return the
    persisted records.

    THIS DOES NOT MAKE A DOC DISAGREEMENT BLOCKING FOR COMMITTAL, and nothing
    about `verify_address_map`/`emit_verified_base_addr_defines` changes: a
    verified entry is still returned, and its `` `define `` is still emitted.
    The two are different questions, and conflating them is what left this
    gap open for so long:

      * "Which base address do I use?" -- decided, mechanically, by the
        authority order (decoder tier 3 > doc tier 6). Never blocks. This is
        the question this module was already answering correctly.
      * "Which of these two artifacts is wrong?" -- NOT decidable by the
        authority order, and left entirely unasked until now. A stale
        register document silently outlived every generation run because the
        only record of the disagreement was a `//` comment in generated
        Verilog that a reader had to already be looking at.

    The queue's Tier-3 `affects_spec_intent` trigger fires on the second
    question, so the resulting entry is blocking for SIGN-OFF (it appears in
    `build_digest()` and the blocking-question metrics) while the generator
    itself runs to completion.
    """
    from .. import source_authority as sa

    records = []
    for e in verified_entries or []:
        if e.get("doc_status") != "DISAGREES":
            continue
        conflict = doc_disagreement_conflict(e, doc_source=doc_source)
        rec = sa.escalate_conflict(
            question_store, conflict, domain="dut",
            subject=f"{e['instance']} register base address",
            context_path=e["decoder_evidence"], now=now,
        )
        if rec is not None:
            records.append(rec)
    return records


def verify_address_map(decoder_entries, bfm_access_histogram, register_doc_entries=None,
                       question_store=None):
    """Cross-check every decoder-claimed register base address against the
    BFM-access histogram (mandatory) and a register document (corroboration
    only), per SKILL.md's three-independent-source method.

    `decoder_entries`: list of {"instance", "base", "evidence"} -- "evidence"
    is the mandatory file:line citation of the address comparator itself
    (never the slave, never a filename/comment guess -- SKILL.md's "find the
    address comparator, not the slave"). Optionally
    "zero_access_override_reason": a non-empty string explicitly
    acknowledging that no BFM pattern currently exercises this base (e.g. a
    feature not yet under test) -- without it, a decoder-claimed base with a
    zero-count histogram entry is refused, not silently trusted.

    `bfm_access_histogram`: list of {"base", "access_count", "source"} --
    see `_index_histogram`.

    `register_doc_entries`: optional list of {"instance", "base", "doc_ref"}.

    Returns a list of verified entries, one per `decoder_entries` item, each:
    {"instance", "base" (int), "base_hex", "decoder_evidence",
     "histogram_access_count", "histogram_source",
     "doc_status": "AGREES" | "DISAGREES" | "NOT_AVAILABLE",
     "doc_ref": str | None}

    Raises AddressMapVerificationError (never silently downgrades or drops
    an entry) on: missing decoder evidence, an unparseable base address, a
    histogram entry missing its own evidence, or a decoder-claimed base with
    zero corroborating BFM accesses and no explicit override reason. A
    register-doc disagreement is recorded in "doc_status", never raised --
    the document corroborates, it does not decide.

    `question_store` (a `question_queue.QuestionQueueStore` or a project-root
    path): when supplied, every DISAGREES entry is ALSO escalated into the
    real question queue by `escalate_doc_disagreements()` -- the "which of
    these two artifacts is wrong" question the doc_status comment never
    asked anyone. Still non-blocking here: the escalation runs AFTER every
    entry is verified, and this function's return value is byte-identical
    with or without it. See `escalate_doc_disagreements`' docstring for why
    "not blocking for committal" and "not worth asking about" are not the
    same claim.
    """
    histogram_index = _index_histogram(bfm_access_histogram)
    doc_index = _index_register_doc(register_doc_entries)

    if not decoder_entries:
        raise AddressMapVerificationError("NO_DECODER_ENTRIES", {})

    verified = []
    for i, entry in enumerate(decoder_entries):
        instance = entry.get("instance")
        if not instance:
            raise AddressMapVerificationError("MISSING_DECODER_EVIDENCE", {
                "index": i, "field": "instance",
            })
        if "base" not in entry:
            raise AddressMapVerificationError("MISSING_DECODER_EVIDENCE", {
                "index": i, "instance": instance, "field": "base",
            })
        if not entry.get("evidence"):
            raise AddressMapVerificationError("MISSING_DECODER_EVIDENCE", {
                "index": i, "instance": instance, "field": "evidence",
            })

        base = _normalize_base(entry["base"], context=f"decoder_entries[{i}] ({instance})")

        hist = histogram_index.get(base)
        access_count = hist["access_count"] if hist else 0
        override_reason = entry.get("zero_access_override_reason")
        if access_count <= 0 and not override_reason:
            raise AddressMapVerificationError("ZERO_ACCESS_HISTOGRAM", {
                "instance": instance, "base_hex": hex(base),
                "decoder_evidence": entry["evidence"],
                "resolution": (
                    "No BFM pattern access counted at this base. Either the "
                    "decoder evidence or the base address is wrong, or this "
                    "block is genuinely never exercised yet -- if the latter, "
                    "set zero_access_override_reason explicitly."
                ),
            })

        doc_entry = doc_index.get(instance)
        if doc_entry is None:
            doc_status, doc_ref = "NOT_AVAILABLE", None
        elif doc_entry["base"] == base:
            doc_status, doc_ref = "AGREES", doc_entry["doc_ref"]
        else:
            doc_status, doc_ref = "DISAGREES", doc_entry["doc_ref"]

        verified.append({
            "instance": instance,
            "base": base,
            "base_hex": hex(base),
            "decoder_evidence": entry["evidence"],
            "histogram_access_count": access_count,
            "histogram_source": hist["source"] if hist else None,
            "zero_access_override_reason": override_reason,
            "doc_status": doc_status,
            "doc_ref": doc_ref,
        })

    if question_store is not None:
        escalate_doc_disagreements(verified, question_store)

    return verified


def emit_verified_base_addr_defines(verified_entries, ip_prefix: str) -> str:
    """Emits `` `define <IP_PREFIX>_<INSTANCE>_BASE_ADDR 32'h... `` for every
    entry `verify_address_map` returned -- i.e. only for base addresses that
    already passed the three-source cross-check. A DISAGREES doc_status is
    still emitted (the doc never decides) but flagged loudly in a comment so
    the disagreement stays visible in the generated file, not just in a log
    a reader may never open."""
    if not verified_entries:
        raise AddressMapVerificationError("NO_VERIFIED_ENTRIES", {})
    lines = [
        "// GENERATED by dv_harness/uvm_generator/address_map_verifier.py --",
        "// every base address below passed the three-independent-source check",
        "// (decoder + BFM-access histogram, mandatory; register doc, corroboration",
        "// only) from CORE/ip-uvm-dv-gen/SKILL.md's address-map method.",
        "",
    ]
    for e in verified_entries:
        define_name = f"{ip_prefix.upper().rstrip('_')}_{e['instance'].upper()}_BASE_ADDR"
        lines.append(f"// decoder: {e['decoder_evidence']}")
        lines.append(
            f"// histogram: {e['histogram_access_count']} access(es)"
            + (f" via {e['histogram_source']}" if e["histogram_source"] else "")
            + (f" -- OVERRIDE: {e['zero_access_override_reason']}" if e["zero_access_override_reason"] else "")
        )
        if e["doc_status"] == "DISAGREES":
            lines.append(
                f"// ** DOC DISAGREEMENT (not blocking -- doc corroborates, never decides): "
                f"{e['doc_ref']} disagrees with the decoder+histogram-verified base **"
            )
        elif e["doc_status"] == "AGREES":
            lines.append(f"// doc corroborates: {e['doc_ref']}")
        else:
            lines.append("// doc: NOT_AVAILABLE")
        lines.append(f"`define {define_name} 32'h{e['base']:08x}")
        lines.append("")
    return "\n".join(lines)
