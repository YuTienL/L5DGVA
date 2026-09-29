"""Phase 12 large-artifact policy, enforced at MEMORY WRITE TIME.

CLAUDE.md's Engineering Memory Policy states the rule this module makes into
enforced code rather than trusted writer discipline:

    "Store giant logs or raw FSDB content in a memory record or vault note --
     cite a path/offset/signature only."

Before this module that rule held only by (a) every existing writer
voluntarily storing `JobState.sim_log`/`fsdb_path` as PATH STRINGS
(`lsf_client._upsert_job_tier_memory_record()`), and (b)
`memory_doctor.check_large_files()`'s POST-HOC scan, which walks the Markdown
vault tree on disk and therefore can never see a raw log body embedded inside
a `.dv-harness/memory/**/<memory_id>.json` record's string field. Nothing
stopped a future/careless caller from embedding one, and once embedded it
would be committed, mirrored into the vault note body, and pushed to the
shared Knowledge Center.

Two enforcement levels, deliberately different in severity:

  * HARD REJECT (`EmbeddedArtifactError`) for content that can only be a raw
    binary/waveform dump -- a NUL byte, or a full VCD value-change body.
    There is no legitimate reading of such content inside a memory record, so
    truncating it would just silently keep a smaller piece of a violation.
  * TRUNCATE (recorded, never silent) for oversized free text -- a pasted
    sim.log body is legitimate CONTENT in the wrong PLACE, and the record it
    arrived on is usually otherwise real. The head and the tail (where a
    UVM epilogue lives) are kept, the middle is replaced by an explicit
    marker naming this policy, and the affected field names are stamped onto
    the record as `large_artifact_truncated` so the truncation is visible in
    the record itself rather than inferred from a length.

`build_evidence_reference()` is the other half of the same policy: the
spec's `evidence: {sim_log, fsdb, coverage, lsf_job}` reference block, as one
shared builder that accepts PATHS/IDS ONLY and raises if handed content.

The forbidden-artifact extension list lives here as the single definition;
`memory_doctor.check_large_files()` imports it rather than keeping its own
copy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Artifact file extensions that must never appear inside a Markdown knowledge
# vault at ANY size, and that must never be embedded as content in a memory
# record. Waveform dumps, coverage/simulation databases, and simulator
# working DBs -- every one of them is referenced by path, never carried.
FORBIDDEN_ARTIFACT_EXTENSIONS = {".fsdb", ".vpd", ".vdb", ".shm", ".db", ".wdb", ".fsdb.gz", ".vcd"}

# Size thresholds for memory_doctor's on-disk vault scan (kept here with the
# extension list so the whole Phase 12 policy has one home).
LARGE_FILE_SIZE_BYTES = 5 * 1024 * 1024   # 5 MB -- any other non-.md file past this size
HUGE_LOG_SIZE_BYTES = 20 * 1024 * 1024    # 20 MB -- a plain .log/.txt only flagged past this size

# Write-time caps for a single string value inside a memory record. A record
# field carries a condensed, reusable engineering claim (a symptom, a root
# cause, a terminal signature, one example log line) -- not a log body. These
# are deliberately generous: the largest legitimate field this repo actually
# writes today is a `terminal_signature` / `example_line` (a few hundred
# characters at most, see sim_log_analysis.parse_sim_log_file()).
MAX_RECORD_FIELD_CHARS = 8000
MAX_RECORD_FIELD_LINES = 200
_TRUNCATION_HEAD_CHARS = 6000
_TRUNCATION_TAIL_CHARS = 1500
_TRUNCATION_HEAD_LINES = 150
_TRUNCATION_TAIL_LINES = 40

# A reference is a path or an id: one line, and short. Anything longer or
# multi-line handed to build_evidence_reference() is content, not a reference.
MAX_EVIDENCE_REFERENCE_CHARS = 4096

# The spec's evidence reference block, in its spec-named order. `coverage`
# has NO real producer anywhere in this repo today (no code path records a
# per-job coverage-database path -- coverage_analysis.py explicitly refuses
# to fabricate one), so in practice it is omitted by build_evidence_reference()
# rather than written as a null placeholder. The key stays in the contract so
# a future real coverage producer has one agreed name to write to instead of
# inventing a second one.
EVIDENCE_REFERENCE_FIELDS = ("sim_log", "fsdb", "coverage", "lsf_job")

# Record keys never scanned/truncated: structural identity and bookkeeping
# fields written by MemoryStore.add() itself. None of them can hold artifact
# content, and mangling `memory_id` would break record identity.
_STRUCTURAL_KEYS = {
    "memory_id", "level", "created_at", "last_used_at", "reuse_count",
    "status", "confirmation_count", "last_confirmed_at",
}


class EmbeddedArtifactError(ValueError):
    """A memory record carried raw binary/waveform-dump content in a field.

    Raised (never silently repaired) by `enforce_record_artifact_policy()`.
    """


def _binary_artifact_reason(text: str) -> Optional[str]:
    """Why this string can only be raw artifact content, or None.

    Two checks, both unambiguous -- no size heuristic here (size is handled
    by truncation, which is a different, softer judgement):
      * a NUL byte: no text a memory record legitimately carries contains
        one; every real writer in this repo stores UTF-8 text or a path.
      * a VCD value-change body: `$enddefinitions` plus `$dumpvars` together
        only ever appear in an actual VCD dump, never in prose about one.
    """
    if "\x00" in text:
        return "EMBEDDED_BINARY_CONTENT (NUL byte in a memory-record string field)"
    if "$enddefinitions" in text and "$dumpvars" in text:
        return "EMBEDDED_VCD_DUMP ($enddefinitions + $dumpvars in a memory-record string field)"
    return None


def _truncate_oversized(text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Bound one oversized string, keeping head AND tail.

    Tail matters specifically for sim.log-shaped text: the UVM epilogue
    (`UVM_FATAL = n, UVM_ERROR = n` / `VERDICT:`) that decides PASS/FAIL sits
    at the very end, so a head-only truncation would throw away the single
    most useful line in the blob it is rejecting.
    """
    lines = text.splitlines()
    detail: Optional[Dict[str, Any]] = None
    original_chars = len(text)
    original_lines = len(lines)
    out = text
    if original_lines > MAX_RECORD_FIELD_LINES:
        dropped = original_lines - _TRUNCATION_HEAD_LINES - _TRUNCATION_TAIL_LINES
        out = "\n".join(
            lines[:_TRUNCATION_HEAD_LINES]
            + [f"...[{dropped} lines removed by the Phase 12 large-artifact policy: "
               f"reference the artifact path, never its content]..."]
            + lines[-_TRUNCATION_TAIL_LINES:]
        )
    if len(out) > MAX_RECORD_FIELD_CHARS:
        dropped = len(out) - _TRUNCATION_HEAD_CHARS - _TRUNCATION_TAIL_CHARS
        out = (out[:_TRUNCATION_HEAD_CHARS]
               + f"\n...[{dropped} characters removed by the Phase 12 large-artifact policy: "
                 f"reference the artifact path, never its content]...\n"
               + out[-_TRUNCATION_TAIL_CHARS:])
    if out != text:
        detail = {"original_chars": original_chars, "original_lines": original_lines,
                   "kept_chars": len(out)}
    return out, detail


def _walk(value: Any, path: str, truncated: List[Dict[str, Any]]) -> Any:
    if isinstance(value, str):
        reason = _binary_artifact_reason(value)
        if reason:
            raise EmbeddedArtifactError(f"{path}: {reason}")
        out, detail = _truncate_oversized(value)
        if detail is not None:
            truncated.append({"field": path, **detail})
        return out
    if isinstance(value, dict):
        return {k: (v if k in _STRUCTURAL_KEYS
                    else _walk(v, f"{path}.{k}" if path else str(k), truncated))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(v, f"{path}[{i}]", truncated) for i, v in enumerate(value)]
    return value


def enforce_record_artifact_policy(record: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Write-time gate for one memory record. Returns (record_out, report).

    `report` is `{"truncated_fields": [...]}` -- empty for the overwhelmingly
    common case of a record whose every field is already a condensed claim or
    a path, in which case `record_out` is value-equal to `record` and nothing
    is stamped onto it.

    Raises `EmbeddedArtifactError` for raw binary/waveform-dump content --
    see `_binary_artifact_reason()` for exactly what that means and why those
    two signals are not merely truncated.
    """
    truncated: List[Dict[str, Any]] = []
    out = _walk(dict(record), "", truncated)
    return out, {"truncated_fields": truncated}


def build_evidence_reference(*, sim_log: Optional[str] = None, fsdb: Optional[str] = None,
                              coverage: Optional[str] = None, lsf_job: Optional[Any] = None,
                              run_dir: Optional[str] = None) -> Dict[str, Any]:
    """The spec's `evidence: {sim_log, fsdb, coverage, lsf_job}` block, built
    in ONE place so every writer produces the same shape.

    PATHS AND IDS ONLY. Every value is checked against
    `MAX_EVIDENCE_REFERENCE_CHARS` and rejected if it spans multiple lines --
    handing this function a log BODY instead of a log PATH raises
    `EmbeddedArtifactError` rather than quietly building an "evidence"
    reference that is itself the artifact.

    A key whose source genuinely captured nothing is OMITTED, never written
    as `None`: the same convention `_upsert_job_tier_memory_record()` already
    uses for seed/fsdb_path, so a reader can tell "not captured" apart from
    "captured as null". `run_dir` is included beyond the four spec-named keys
    because it is the directory the other three live under and this repo's
    JobState already records it -- omitted like the rest when absent.
    """
    out: Dict[str, Any] = {}
    for key, value in (("sim_log", sim_log), ("fsdb", fsdb), ("coverage", coverage),
                        ("lsf_job", lsf_job), ("run_dir", run_dir)):
        if value is None or value == "":
            continue
        text = str(value)
        if "\n" in text or "\r" in text:
            raise EmbeddedArtifactError(
                f"evidence.{key}: multi-line value is content, not a path/id reference")
        if len(text) > MAX_EVIDENCE_REFERENCE_CHARS:
            raise EmbeddedArtifactError(
                f"evidence.{key}: {len(text)} characters is content, not a path/id reference")
        out[key] = value
    return out
