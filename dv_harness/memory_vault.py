"""Obsidian+Git/Markdown Hybrid Engineering Memory -- foundational layer.

This module is the FOUNDATIONAL layer (Workstream 1 of 4) for the
Obsidian-compatible, git-friendly Markdown Vault described in the project's
integration spec. It is deliberately independent of `dv_harness/memory.py`'s
JSON-file MemoryStore (which remains the system of record for every existing
gate/router/skill) -- this module adds an ADDITIVE, human-browsable Markdown
representation on top, never a replacement.

What lives here, matching the 4 phases this workstream owns:

  Phase 2 -- Obsidian CLI capability detection: `detect_obsidian_cli()`.
    Confirmed NOT_INSTALLED on this development machine (2026-09-03
    controller discovery: `where obsidian-cli` / `where obsidian` both
    failed), but the probe itself is real and general (PATH lookup +
    well-known per-OS install locations, real `--version`/`-v` subprocess
    invocation) -- it will correctly report `installed: True` and a real
    version string on any machine that genuinely has one installed.

  Phase 3 -- DV-Knowledge Vault bootstrap: `VAULT_STRUCTURE`,
    `bootstrap_vault()`, `resolve_vault_path()`. The vault path is never
    hardcoded (same convention as `config.py`'s `knowledge_center.remote_root`
    and `rtl_protection.protected_paths`): it comes from
    `.dv-harness/config.json`'s new `memory.vault_path`, or -- when that is
    left empty, the honest default for a project that hasn't configured one
    yet -- a project-relative `.dv-harness/vault` (never an external
    absolute path this module invents on its own).

  Phase 7 -- Memory note schema: `MEMORY_NOTE_REQUIRED_FIELDS` /
    `MEMORY_NOTE_OPTIONAL_FIELDS` / `MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS` /
    `MEMORY_NOTE_BODY_SECTIONS`, `validate_note_frontmatter()`,
    `validate_note_body_sections()`, `validate_note()`,
    `render_note_markdown()` / `parse_note_markdown()`. A note missing a
    required field is written with `schema_status: PARTIAL` baked into its
    own frontmatter -- never silently written as if it were complete. The
    body's 11-section shape is guaranteed by construction on WRITE
    (`render_note_markdown()`) and independently re-checked on READ
    (`validate_note_body_sections()`, run by `memory_doctor.check_schema()`),
    so a note hand-edited in Obsidian that loses a `## Fix` header is caught
    rather than trusted.

  Phase 8 -- Obsidian CLI Adapter: the `MemoryProvider` interface plus
    `ObsidianAdapter` (thin, honest capability probing, every operational
    method a clear NOT_AVAILABLE result -- see `ObsidianAdapter`'s own
    docstring for why operations are never speculatively wired),
    `FileSystemMarkdownAdapter` (the real, fully-functional implementation
    against actual Markdown+YAML files), and `HybridMemoryProvider` (what
    every real caller -- `memory_router.py`'s write-through, and the future
    Memory Agent -- actually holds: tries Obsidian per call when its own
    `status()` is READY, falls back to the filesystem adapter whenever that
    call itself is not actually available).

Workstream-2 addendum (2026-09-03, CLI/health-check/dedup/security pass):
`FileSystemMarkdownAdapter.create()`/`update()` now redact secret-shaped
content via `dv_harness/memory_security.py` before writing (Phase 19), and
`dv_harness/memory_dedup.py` (Phase 18) and `dv_harness/memory_doctor.py`
(Phase 21) read real notes out of this module's vault layout to classify
new-knowledge candidates and run the `memory doctor` health check,
respectively -- both additive, neither changes this module's own schema or
provider contract.

Workstream-3 addendum (2026-09-03, debug-flow/regression-memory/git-policy/
session pass): three additive extensions, none changing the Phase 2/3/7/8
contract above --
  (a) `create()`/`update()`/`delete()` gained an optional `commit_message`
      parameter (Phase 13): a policy-aware caller (`memory_router.py`'s
      `_maybe_write_vault_note()`) supplies the real
      `memory(<protocol>): <short description>` commit-message format;
      omitting it (every pre-existing caller) reproduces the prior generic
      message unchanged. `_commit_vault_change()` now returns the real
      resulting commit SHA (`git rev-parse HEAD`), surfaced as
      `knowledge_commit_sha` in the result dict, for `memory_router.py` to
      write back onto the underlying JSON MemoryStore record for
      traceability alongside `rtl_sha`/`tb_sha` (see `MEMORY_NOTE_OPTIONAL_
      FIELDS`' own comment, and `memory_router._write_back_knowledge_commit_
      sha()`). Since 2026-09-04 that commit is RETRIED on a transient git
      failure and its outcome is REPORTED
      (`_commit_vault_change_detailed()` / `apply_commit_outcome()` ->
      `knowledge_commit_status`), because an absent `knowledge_commit_sha`
      used to mean "git off", "nothing changed" and "the commit failed"
      indistinguishably -- and only the last of those is a real
      traceability defect.
  (b) `build_failure_signature()`/`search_related_memory_for_debug()` (Phase
      10/11, bottom of this file): the shared "search prior knowledge for a
      failure" interface engine.py's debug flow and lsf_client.py's
      regression-job memory extraction both call -- see their own
      docstrings.
  (c) `MEMORY_NOTE_OPTIONAL_FIELDS` gained `knowledge_commit_sha` (item (a)
      above needed a schema field to carry it).

No embedding/vector database is used or added anywhere in this module --
`FileSystemMarkdownAdapter.search()` is real keyword/tag/YAML-property/
wiki-link/exact filtering over the real files, optionally accelerated by
`rg` when present on PATH, with a full pure-Python filesystem scan as the
always-correct fallback.

This module has ZERO new third-party dependencies (stdlib only, matching
`requirements-harness.txt`'s "Core harness uses Python standard library
only" -- PyYAML is present in this dev environment but is NOT declared as a
harness dependency, so it is not imported here). YAML frontmatter is
produced/consumed by a small, intentionally-scoped subset implemented below
(`_scalar_dump`/`_scalar_load`/`_frontmatter_dumps`/`_frontmatter_loads`):
scalars (str/int/float/bool/None) and flat lists of scalars, which is
exactly what this note schema needs -- it is not a general YAML parser and
must never be used as one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .memory import _tok as _tokenize  # reuse the existing stopword-aware tokenizer, not a second copy


# ---------------------------------------------------------------------------
# Phase 7: Memory Note Schema
# ---------------------------------------------------------------------------

# Required per the user's spec -- absence of ANY of these forces
# schema_status="PARTIAL" (see validate_note_frontmatter()). "protocol",
# "status" and "confidence" are required because a memory note that does not
# say WHICH protocol it applies to, whether it is still trusted, or how
# confident it is, is not yet reusable knowledge -- exactly the bar
# CLAUDE.md's "memory is prior knowledge, not current evidence" already sets
# for anything read back out of Memory. "applies to no particular protocol"
# is itself one of those answers, and has its own value (GENERAL_PROTOCOL
# below) rather than being left blank.
MEMORY_NOTE_REQUIRED_FIELDS = ["id", "memory_level", "protocol", "status", "confidence", "created", "updated"]

# The answer a record that is genuinely not protocol-specific (a harness-
# engine or process lesson) gives to the required `protocol` field. NOT a
# fabricated protocol name: `_general` is a real registered
# `knowledge_center.categories` entry (config.py's DEFAULT_CONFIG), it is
# already the value the vault's OWN git commit carries for such a record
# (`memory(_general): ...`, memory_router._build_vault_commit_message()),
# and it is already the protocol such a record is pushed to the shared
# Knowledge Center under (memory_router._maybe_share(), memory.py's
# SharedKnowledgeMemoryStore.add()).
#
# build_frontmatter_from_memory_record() was the one place in that same
# write path that did NOT apply it, emitting `protocol: null` instead. The
# measured consequence (2026-09-04): all 9 of this project's real vault
# notes were schema_status PARTIAL, every one of them on `protocol` alone,
# on a field the write path already had an honest answer for -- and
# `dv-harness memory search --protocol ...` could not reach any of them,
# because null matches no filter.
GENERAL_PROTOCOL = "_general"

# Optional -- present when the originating record/caller has them, never
# required for a note to be written, but always emitted (as null) so a
# reader/Obsidian's own Properties view sees the full schema shape even on a
# sparse note.
#
# `knowledge_commit_sha` (Phase 13 -- Git Integration, 2026-09-03): the
# DV-Knowledge Vault's OWN git commit SHA that captured this record, for
# cross-referencing alongside rtl_sha/tb_sha (CLAUDE.md's "same regression
# batch must use the same source/build/config identity", extended here to
# "and the same knowledge-vault commit that recorded it"). Populated by
# memory_router.py's write-back AFTER a real vault commit happens (see
# _write_back_knowledge_commit_sha() there) -- never guessed here, and never
# by re-committing the note itself a second time to embed its own just-made
# SHA (that would be circular); this field lives on the note's frontmatter
# only when a later re-render (e.g. an update() call) happens to carry it
# through from the underlying record.
MEMORY_NOTE_OPTIONAL_FIELDS = [
    "subsystem", "category", "failure", "project", "rtl_sha", "tb_sha",
    "vip_vendor", "vip_version", "simulator", "tags", "knowledge_commit_sha",
]

MEMORY_NOTE_ALL_FIELDS = MEMORY_NOTE_REQUIRED_FIELDS + MEMORY_NOTE_OPTIONAL_FIELDS

# The user's Phase 7 spec text lists these nine as "required"; this module
# deliberately keeps them OPTIONAL for gating purposes (see
# MEMORY_NOTE_REQUIRED_FIELDS' comment above -- only the identity/trust
# fields decide whether a note is reusable knowledge at all, and a real
# debug lesson with no `rtl_sha` is still reusable knowledge). They are
# nonetheless REPORTED as absent by validate_note_frontmatter()'s
# `missing_recommended`, so the spec's fuller list is genuinely checked and
# surfaced (`dv-harness memory doctor`/`validate`) rather than unvalidated --
# it just never flips schema_status on its own.
# `tags` and `knowledge_commit_sha` are excluded on purpose: `tags` is
# derived by the router rather than sourced from the record, and
# `knowledge_commit_sha` only exists AFTER a real vault commit, so reporting
# either as "absent" would be noise on every correctly-written note.
MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS = [
    f for f in MEMORY_NOTE_OPTIONAL_FIELDS if f not in ("tags", "knowledge_commit_sha")
]

# Field order used only for rendering — required first, then optional, then
# the adapter-computed bookkeeping fields (schema_status is always written
# by the adapter itself, never supplied by a caller: see
# FileSystemMarkdownAdapter.create()/update()). Any OTHER key present on a
# frontmatter dict (e.g. confirmation_count/last_confirmed_at, carried
# through from the originating MemoryStore record) is still emitted, just
# appended after this fixed set, so no caller-supplied data is ever dropped.
_NOTE_FIELD_RENDER_ORDER = MEMORY_NOTE_ALL_FIELDS + ["schema_status", "confirmation_count", "last_confirmed_at"]

MEMORY_NOTE_BODY_SECTIONS = [
    "Symptom", "Context", "Hypothesis", "Evidence", "Root Cause", "Fix",
    "Verification", "Confidence", "Reusability", "Known Limitations", "Related Knowledge",
]

NOTE_ID_PREFIX = "NOTE"


def _gen_note_id() -> str:
    return f"{NOTE_ID_PREFIX}-{uuid.uuid4().hex[:10].upper()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _epoch_to_iso(epoch: Any) -> Optional[str]:
    if epoch in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def validate_note_frontmatter(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    """Real schema validation (Phase 7's explicit requirement): a note
    missing any MEMORY_NOTE_REQUIRED_FIELDS value is flagged PARTIAL here --
    the caller (FileSystemMarkdownAdapter.create()/update()) bakes this
    result's `schema_status` directly into the written note's own
    frontmatter, so the incompleteness is visible on the note itself, not
    merely returned once and forgotten.

    `missing_recommended` reports the MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS the
    note does not carry. It is REPORT-ONLY and never affects `schema_status`
    -- see that constant's own comment for why those nine fields are checked
    but not gated on."""
    missing = [f for f in MEMORY_NOTE_REQUIRED_FIELDS if frontmatter.get(f) in (None, "")]
    missing_recommended = [f for f in MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS if frontmatter.get(f) in (None, "")]
    return {"schema_status": "PARTIAL" if missing else "COMPLETE", "missing_required": missing,
            "missing_recommended": missing_recommended}


# --- Minimal, intentionally-scoped YAML-frontmatter subset -----------------
# Supports exactly what this schema needs: scalar str/int/float/bool/None,
# and flat lists of such scalars (used only by `tags`). Deliberately NOT a
# general YAML parser/dumper -- nested maps, multi-line block scalars,
# anchors, etc. are out of scope and unsupported. Round-trips only with
# ITSELF (`_frontmatter_dumps` -> `_frontmatter_loads`), which is the only
# contract this module needs: every note this adapter ever reads was also
# written by this adapter (or is a schema-shaped file a human hand-edited
# in Obsidian using the same simple `key: value` / `key:\n  - item` shapes,
# which real Obsidian frontmatter also uses for simple properties).

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")


def _needs_quoting(s: str) -> bool:
    if s == "" or s.strip() != s:
        return True
    if s in ("null", "~", "true", "false", "True", "False"):
        return True
    if _INT_RE.match(s) or _FLOAT_RE.match(s):
        return True
    if s[0] in "\"'[]{}#&*!|>%@`" or s.startswith("- "):
        return True
    if ": " in s or s.endswith(":") or "\n" in s:
        return True
    return False


def _scalar_dump(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if _needs_quoting(s):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return s


def _scalar_load(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        inner = text[1:-1]
        return inner.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    if text in ("null", "~", ""):
        return None
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return text


def _frontmatter_dumps(fm: Dict[str, Any]) -> str:
    lines = ["---"]
    ordered_keys = [k for k in _NOTE_FIELD_RENDER_ORDER if k in fm]
    ordered_keys += [k for k in fm.keys() if k not in _NOTE_FIELD_RENDER_ORDER]
    for key in ordered_keys:
        val = fm[key]
        if isinstance(val, list):
            if not val:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_scalar_dump(item)}" for item in val)
        else:
            lines.append(f"{key}: {_scalar_dump(val)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _frontmatter_loads(text: str) -> Dict[str, Any]:
    fm: Dict[str, Any] = {}
    last_key: Optional[str] = None
    for line in text.splitlines():
        if line.strip() in ("---", ""):
            continue
        if line.startswith("  - "):
            if last_key is not None:
                if not isinstance(fm.get(last_key), list):
                    fm[last_key] = []
                fm[last_key].append(_scalar_load(line[4:]))
            continue
        m = _FRONTMATTER_KEY_RE.match(line)
        if not m:
            continue
        key, rest = m.group(1), m.group(2).strip()
        # A bare "key:" (nothing after the colon) always means "an empty
        # list, or a list whose items follow as '  - item' lines" in
        # OUR OWN dumper's output -- _scalar_dump() never emits a bare
        # empty-string scalar this way (empty strings are always quoted
        # as `""`), so this is unambiguous for anything this module wrote.
        fm[key] = [] if rest in ("", "[]") else _scalar_load(rest)
        last_key = key
    return fm


def render_note_markdown(frontmatter: Dict[str, Any], sections: Optional[Dict[str, str]] = None) -> str:
    """Phase 7's body template: fixed Symptom/Context/.../Related Knowledge
    section headers, each populated from `sections` (plain strings --
    callers wanting bullet lists or `[[WikiLink]]` entries pre-format them,
    see memory_router.py's build_sections_from_memory_record()) or a
    clearly-marked placeholder when not yet documented."""
    sections = sections or {}
    body_parts: List[str] = []
    for name in MEMORY_NOTE_BODY_SECTIONS:
        body_parts.append(f"## {name}")
        content = sections.get(name)
        body_parts.append(str(content) if content not in (None, "") else "_Not yet documented._")
        body_parts.append("")
    return _frontmatter_dumps(frontmatter) + "\n" + "\n".join(body_parts).rstrip() + "\n"


def parse_note_markdown(text: str) -> Tuple[Dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text
    fm = _frontmatter_loads("\n".join(lines[: end_idx + 1]))
    body = "\n".join(lines[end_idx + 1:]).lstrip("\n")
    return fm, body


def _body_to_sections(body: str) -> Dict[str, str]:
    """Inverse of render_note_markdown()'s body layout -- used by
    FileSystemMarkdownAdapter.update() so a partial `sections_patch` only
    overwrites the named sections, preserving every other section's
    existing content instead of blanking it back to placeholders."""
    sections: Dict[str, str] = {}
    current: Optional[str] = None
    buf: List[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def validate_note_body_sections(body: Optional[str]) -> Dict[str, Any]:
    """Phase 7's OTHER half of the schema contract, checked on READ.

    `render_note_markdown()` guarantees the 11 MEMORY_NOTE_BODY_SECTIONS in
    the right order by construction, so every note this adapter writes is
    correct the moment it is written. That guarantee covers exactly one code
    path: a note hand-edited afterwards in the Obsidian GUI (or by any other
    tool) can lose a `## Fix` header, reorder sections, or arrive as a bare
    frontmatter block with no body at all, and nothing would notice. This
    function is what notices -- `memory_doctor.check_schema()` runs it over
    every real note on disk, exactly as it already runs
    `validate_note_frontmatter()` over every note's frontmatter.

    `body_status` is PARTIAL when a required section header is missing OR
    the required headers appear out of the canonical order (order matters:
    the sections are a reasoning sequence -- Symptom before Hypothesis
    before Root Cause before Fix before Verification -- not an unordered
    bag). EXTRA `##` headers a human added are reported in
    `unexpected_sections` but never downgrade the status: adding a section
    is not a schema violation, deleting or reshuffling one is."""
    present_order = list(_body_to_sections(body or ""))  # dict preserves the body's own header order
    present = set(present_order)
    missing = [name for name in MEMORY_NOTE_BODY_SECTIONS if name not in present]
    unexpected = [name for name in present_order if name not in MEMORY_NOTE_BODY_SECTIONS]
    required_in_body_order = [name for name in present_order if name in MEMORY_NOTE_BODY_SECTIONS]
    canonical_order = [name for name in MEMORY_NOTE_BODY_SECTIONS if name in present]
    out_of_order = required_in_body_order != canonical_order
    return {
        "body_status": "PARTIAL" if (missing or out_of_order) else "COMPLETE",
        "missing_sections": missing,
        "unexpected_sections": unexpected,
        "out_of_order": out_of_order,
    }


def validate_note(frontmatter: Dict[str, Any], body: Optional[str] = None) -> Dict[str, Any]:
    """Whole-note Phase 7 validation: frontmatter fields AND body shape.

    `note_status` is COMPLETE only when BOTH halves are -- this is the single
    verdict a reader should act on. The two halves stay separately reported
    (`schema_status` / `body_status`) because they fail for different reasons
    and have different fixes: a missing required field is repaired by
    re-writing the note from its source record, a missing/reordered section
    is repaired by editing the note's body."""
    fm_result = validate_note_frontmatter(frontmatter)
    body_result = validate_note_body_sections(body)
    complete = fm_result["schema_status"] == "COMPLETE" and body_result["body_status"] == "COMPLETE"
    return {"note_status": "COMPLETE" if complete else "PARTIAL", **fm_result, **body_result}


# ---------------------------------------------------------------------------
# Phase 3: DV-Knowledge Vault bootstrap
# ---------------------------------------------------------------------------

VAULT_STRUCTURE = [
    "00_Inbox",
    "01_Projects",
    "02_Protocols/USB", "02_Protocols/PCIe", "02_Protocols/Ethernet",
    "02_Protocols/AMBA", "02_Protocols/MIPI", "02_Protocols/CAN-FD",
    "03_Verification/UVM", "03_Verification/VIP", "03_Verification/vPlan",
    "03_Verification/Coverage", "03_Verification/Regression",
    "04_Debug/Known_Issues", "04_Debug/Failure_Patterns", "04_Debug/Root_Cause",
    "05_Tools/VCS", "05_Tools/Verdi", "05_Tools/ZeBu", "05_Tools/HAPS", "05_Tools/LSF",
    "06_Agent_Memory/Working", "06_Agent_Memory/Job", "06_Agent_Memory/Project",
    "06_Agent_Memory/Engineering", "06_Agent_Memory/Organizational",
    "07_Signoff/Requirements", "07_Signoff/Traceability", "07_Signoff/Coverage", "07_Signoff/Reports",
]

_MEMORY_LEVEL_FOLDER = {
    "working": "06_Agent_Memory/Working",
    "job": "06_Agent_Memory/Job",
    "project": "06_Agent_Memory/Project",
    "engineering": "06_Agent_Memory/Engineering",
    "organizational": "06_Agent_Memory/Organizational",
}


def resolve_vault_path(project_root: Path, cfg: Optional[Dict[str, Any]] = None) -> Path:
    """Never hardcoded (same convention as config.py's knowledge_center.
    remote_root/rtl_protection.protected_paths): reads
    `.dv-harness/config.json`'s `memory.vault_path`. An empty/unset
    vault_path (a project that has not configured one) gets an honest
    project-relative default (`.dv-harness/vault`) rather than guessing at,
    or hardcoding, some external path -- matching how every other per-tier
    memory store in this codebase already defaults under the project root."""
    if cfg is None:
        from .config import load_config
        cfg = load_config(project_root)
    configured = str((cfg.get("memory") or {}).get("vault_path") or "").strip()
    if configured:
        p = Path(configured).expanduser()
        if not p.is_absolute():
            p = Path(project_root) / p
        return p.resolve()
    return (Path(project_root) / ".dv-harness" / "vault").resolve()


def bootstrap_vault(vault_path: Path) -> Dict[str, Any]:
    """Creates the full DV-Knowledge Vault directory tree on first use.
    ADDITIVE ONLY: every existing directory/file under vault_path is left
    completely untouched -- this only ever calls mkdir(exist_ok=True), never
    removes or overwrites anything, so re-running it against an
    already-populated vault (real notes, a human's own extra folders) is
    always safe."""
    vault_path = Path(vault_path)
    vault_pre_existing = vault_path.exists()
    vault_path.mkdir(parents=True, exist_ok=True)
    created, already_existed = [], []
    for rel in VAULT_STRUCTURE:
        d = vault_path / rel
        if d.exists():
            already_existed.append(rel)
        else:
            d.mkdir(parents=True, exist_ok=True)
            created.append(rel)
    return {
        "vault_path": str(vault_path),
        "vault_pre_existing": vault_pre_existing,
        "created": created,
        "already_existed": already_existed,
    }


# --- optional git integration (config's memory.git_enabled) ----------------

def _run_git_ex(vault_path: Path, args: List[str],
                timeout: int = 10) -> Tuple[Optional[subprocess.CompletedProcess], Optional[str]]:
    """`_run_git()` plus the REASON the invocation produced no process at all.

    A git invocation must never break a memory write, so the exception is
    still swallowed -- but swallowing it without keeping the reason is what
    made a transient failure (a `subprocess.TimeoutExpired` at the 10s cap
    under machine load, an antivirus-held `index.lock`, git missing from
    PATH mid-run) indistinguishable from the ordinary, expected "there was
    nothing to commit". `_commit_vault_change_detailed()` below needs that
    distinction to decide whether retrying is worth anything and whether the
    caller should be told a commit it expected did not happen."""
    try:
        return subprocess.run(["git"] + args, cwd=str(vault_path), capture_output=True,
                              text=True, timeout=timeout), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _run_git(vault_path: Path, args: List[str], timeout: int = 10) -> Optional[subprocess.CompletedProcess]:
    """The process-only form every non-commit caller uses (`_ensure_git_repo()`
    here, `memory_doctor.check_git()`, `cli.py`'s `memory vault-commit`) --
    unchanged Optional[CompletedProcess] contract."""
    proc, _reason = _run_git_ex(vault_path, args, timeout=timeout)
    return proc


def _ensure_git_repo(vault_path: Path) -> bool:
    if (vault_path / ".git").exists():
        return True
    r = _run_git(vault_path, ["init"])
    if r is None or r.returncode != 0:
        return False
    # Repo-local identity only (never touches the user's global git config)
    # so a fresh vault commits cleanly even on a machine with no global
    # user.name/user.email configured at all.
    _run_git(vault_path, ["config", "user.email", "dv-harness-memory-vault@local"])
    _run_git(vault_path, ["config", "user.name", "DV Harness Memory Vault"])
    return True


# Commit outcomes (Phase 13 traceability, 2026-09-04). Four distinct states,
# never collapsed into "we got no SHA": a missing `knowledge_commit_sha` used
# to mean any of "git is off", "nothing changed", and "the commit really
# failed", and only the last of those is a traceability defect a caller needs
# to see or act on.
COMMIT_STATUS_COMMITTED = "COMMITTED"
COMMIT_STATUS_NOTHING_TO_COMMIT = "NOTHING_TO_COMMIT"
COMMIT_STATUS_SHA_UNRESOLVED = "COMMITTED_SHA_UNRESOLVED"
COMMIT_STATUS_FAILED = "COMMIT_FAILED"

# `git commit` exits non-zero for "nothing to commit" exactly as it does for a
# real error, so the expected/benign case is told apart by git's own message.
_NOTHING_TO_COMMIT_RE = re.compile(
    r"nothing to commit|nothing added to commit|no changes added to commit", re.IGNORECASE)

# The failures this retry exists for are transient by nature (an index.lock
# another process holds for a moment, the 10s subprocess cap under machine
# load). Three attempts with a short backoff costs a fraction of a second on
# the failure path and nothing at all on the success path or the
# NOTHING_TO_COMMIT path, both of which return before ever sleeping.
_GIT_COMMIT_ATTEMPTS = 3
_GIT_RETRY_BACKOFF_SECONDS = 0.2

# git's stderr on a real failure is short, but it is machine output going into
# a memory-write result dict -- bounded for the same reason CLAUDE.md forbids
# giant logs in a memory record.
_GIT_ERROR_DETAIL_MAX_CHARS = 400


def _git_failure_detail(what: str, proc: Optional[subprocess.CompletedProcess]) -> str:
    if proc is None:
        return f"{what}: no process"
    text = ((proc.stderr or "") + " " + (proc.stdout or "")).strip()
    return f"{what} exited {proc.returncode}: {text}"[:_GIT_ERROR_DETAIL_MAX_CHARS]


def _commit_vault_change_detailed(vault_path: Path, message: str,
                                  attempts: int = _GIT_COMMIT_ATTEMPTS) -> Dict[str, Any]:
    """Real commit (Phase 13 -- Git Integration), reporting WHICH of the four
    outcomes above happened instead of only handing back an Optional SHA.

    This exists because the Phase 13 requirement is traceability: a verified
    promotion whose vault commit silently did not happen leaves a durable
    memory record with no `knowledge_commit_sha` and nothing anywhere saying
    why. That was observed for real (2026-09-04) -- a full-suite run under
    load produced a `knowledge_commit_sha: None` on a promotion whose note
    was genuinely new, i.e. a case where `NOTHING_TO_COMMIT` was impossible,
    while the same test passed in isolation. So a transient git failure is
    now (a) retried, and (b) reported as `COMMIT_FAILED` with git's own error
    text rather than being indistinguishable from "nothing changed".

    Never fabricates a SHA. `NOTHING_TO_COMMIT` returns immediately and is
    never retried -- it is the ordinary outcome of an update() that changed
    nothing, not a failure. `COMMITTED_SHA_UNRESOLVED` is its own state
    because the commit in that case really DID land; only reading its SHA
    back failed, and reporting that as a failed commit would be a false
    claim about the repository."""
    detail: Optional[str] = None
    for attempt in range(1, max(1, attempts) + 1):
        add_proc, add_reason = _run_git_ex(vault_path, ["add", "-A"])
        if add_proc is None or add_proc.returncode != 0:
            detail = add_reason or _git_failure_detail("git add -A", add_proc)
        else:
            commit_proc, commit_reason = _run_git_ex(vault_path, ["commit", "-m", message])
            if commit_proc is not None and commit_proc.returncode == 0:
                sha_proc, sha_reason = _run_git_ex(vault_path, ["rev-parse", "HEAD"])
                sha = ((sha_proc.stdout or "").strip()
                       if sha_proc is not None and sha_proc.returncode == 0 else "")
                if sha:
                    return {"status": COMMIT_STATUS_COMMITTED,
                            "knowledge_commit_sha": sha, "attempts": attempt}
                return {"status": COMMIT_STATUS_SHA_UNRESOLVED, "attempts": attempt,
                        "error": sha_reason or _git_failure_detail("git rev-parse HEAD", sha_proc)}
            if commit_proc is not None and _NOTHING_TO_COMMIT_RE.search(
                    (commit_proc.stdout or "") + (commit_proc.stderr or "")):
                return {"status": COMMIT_STATUS_NOTHING_TO_COMMIT, "attempts": attempt}
            detail = commit_reason or _git_failure_detail("git commit", commit_proc)
        if attempt < max(1, attempts):
            time.sleep(_GIT_RETRY_BACKOFF_SECONDS)
    return {"status": COMMIT_STATUS_FAILED, "attempts": max(1, attempts),
            "error": (detail or "git commit produced no result")[:_GIT_ERROR_DETAIL_MAX_CHARS]}


def _commit_vault_change(vault_path: Path, message: str) -> Optional[str]:
    """The SHA-only form, for callers that only need "did we get a commit"
    (`cli.py`'s `memory vault-commit`). Returns None -- never a fabricated
    SHA -- for every non-COMMITTED outcome; use
    `_commit_vault_change_detailed()` when the difference between "nothing
    to commit" and "the commit failed" matters."""
    return _commit_vault_change_detailed(vault_path, message).get("knowledge_commit_sha")


def apply_commit_outcome(result: Dict[str, Any], commit: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a `_commit_vault_change_detailed()` outcome into a provider
    result dict. Public, unlike the git helpers above, because it defines the
    commit-reporting half of the MemoryProvider result contract: any future
    provider that gains real git integration (an ObsidianAdapter that one day
    commits for itself) reports it through this one function rather than
    inventing a second set of key names for the same four outcomes.

    `knowledge_commit_sha` keeps its exact prior meaning and is
    still present only on a real commit; `knowledge_commit_status` is what
    makes an EXPECTED-but-missing commit visible to `memory_router.py` (and
    therefore to `route_and_store()`'s own returned result) rather than
    silent. An empty `commit` -- git integration off -- adds nothing, so a
    git-disabled result is byte-identical to what it was before."""
    if not commit:
        return result
    if commit.get("knowledge_commit_sha"):
        result["knowledge_commit_sha"] = commit["knowledge_commit_sha"]
    result["knowledge_commit_status"] = commit["status"]
    if commit.get("error"):
        result["knowledge_commit_error"] = commit["error"]
    if int(commit.get("attempts") or 1) > 1:
        result["knowledge_commit_attempts"] = commit["attempts"]
    return result


# ---------------------------------------------------------------------------
# Phase 2: Obsidian CLI capability detection
# ---------------------------------------------------------------------------

_OBSIDIAN_CLI_CANDIDATES = ["obsidian-cli", "obsidian"]


def _candidate_install_paths() -> List[Path]:
    """Well-known per-package-manager install locations, checked ONLY when
    a bare PATH lookup (shutil.which, which already honors PATHEXT on
    Windows) finds nothing -- real, existence-checked paths, not asserted.
    The WinGet Links pattern below is not a guess: `where rg` on this exact
    development machine resolved to
    `%LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\rg.exe`, confirming that is a
    real CLI-tool location on this machine's actual PATH-adjacent install
    layout."""
    paths: List[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(Path(local) / "Microsoft" / "WinGet" / "Links" / "obsidian-cli.exe")
        paths.append(Path(local) / "Programs" / "obsidian-cli" / "obsidian-cli.exe")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "npm" / "obsidian-cli.cmd")
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        paths.append(Path(userprofile) / "scoop" / "shims" / "obsidian-cli.exe")
    paths.append(Path("C:/ProgramData/chocolatey/bin/obsidian-cli.exe"))
    try:
        home = Path.home()
        paths.append(home / ".local" / "bin" / "obsidian-cli")
    except Exception:  # pragma: no cover - Path.home() can fail in odd sandboxes
        pass
    paths.append(Path("/usr/local/bin/obsidian-cli"))
    paths.append(Path("/usr/bin/obsidian-cli"))
    return paths


def detect_obsidian_cli() -> Dict[str, Any]:
    """Real, general capability probe -- NOT hardcoded to "not found".
    Confirmed NOT_INSTALLED on this specific development machine (2026-09-03
    controller discovery: `where obsidian-cli` and `where obsidian` both
    failed), but every check below is a genuine filesystem/subprocess
    probe: `installed`/`version`/`executable` will correctly reflect an
    actually-installed CLI on any other machine.

    `search`/`read`/`create`/`update`/`properties`/`tags`/`links` stay
    NOT_AVAILABLE regardless of `installed` -- see ObsidianAdapter's module
    docstring for why: this codebase has never observed a real
    obsidian-cli's command contract, so no method here ever guesses at one.
    `status` therefore also stays PARTIAL even when a CLI binary is found
    (never READY) -- a truthful `installed: True` at the detection layer is
    NOT the same claim as "this adapter can perform real operations against
    it", and this report keeps those two claims visibly distinct rather
    than reporting Status="READY" for a capability nothing here actually
    exercises. Per the spec's explicit requirement, this design intentionally
    means the memory system NEVER blocks on Obsidian's absence -- PARTIAL
    (not BLOCKED) whether or not the binary is present, with the real,
    fully-functional FileSystemMarkdownAdapter always available as the
    actual write path (see HybridMemoryProvider)."""
    try:
        executable = None
        for name in _OBSIDIAN_CLI_CANDIDATES:
            found = shutil.which(name)
            if found:
                executable = found
                break
        if executable is None:
            for candidate in _candidate_install_paths():
                if candidate.exists():
                    executable = str(candidate)
                    break

        version = None
        if executable is not None:
            for flag in ("--version", "-v"):
                try:
                    proc = subprocess.run([executable, flag], capture_output=True, text=True, timeout=5)
                    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
                    if proc.returncode == 0 and out:
                        version = out.splitlines()[0][:200]
                        break
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    continue

        installed = executable is not None and version is not None
        return {
            "installed": installed,
            "version": version,
            "executable": executable,
            "vault_access": False,  # overwritten by ObsidianAdapter.detect() when a vault_path is known
            "search": "NOT_AVAILABLE",
            "read": "NOT_AVAILABLE",
            "create": "NOT_AVAILABLE",
            "update": "NOT_AVAILABLE",
            "properties": "NOT_AVAILABLE",
            "tags": "NOT_AVAILABLE",
            "links": "NOT_AVAILABLE",
            "status": "PARTIAL",
        }
    except Exception as exc:  # pragma: no cover - detection itself must never crash the memory system
        return {
            "installed": False, "version": None, "executable": None, "vault_access": False,
            "search": "NOT_AVAILABLE", "read": "NOT_AVAILABLE", "create": "NOT_AVAILABLE",
            "update": "NOT_AVAILABLE", "properties": "NOT_AVAILABLE", "tags": "NOT_AVAILABLE",
            "links": "NOT_AVAILABLE", "status": "BLOCKED", "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Phase 8: MemoryProvider interface + two real implementations
# ---------------------------------------------------------------------------

class MemoryProvider(ABC):
    """The interface the (future) Memory Agent must depend on exclusively --
    never a hard-coded Obsidian-specific call. Every method returns a plain
    dict carrying at least `"ok": bool` (or, for detect()/status(), a
    capability-report shape) so a caller can branch on outcome without
    needing to catch adapter-specific exceptions."""

    @abstractmethod
    def detect(self) -> Dict[str, Any]: ...

    @abstractmethod
    def status(self) -> Dict[str, Any]: ...

    @abstractmethod
    def search(self, query: Dict[str, Any], limit: int = 8) -> Dict[str, Any]: ...

    @abstractmethod
    def read(self, note_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def create(self, frontmatter: Dict[str, Any], sections: Optional[Dict[str, str]] = None,
               body: Optional[str] = None, commit_message: Optional[str] = None) -> Dict[str, Any]: ...

    @abstractmethod
    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None,
               commit_message: Optional[str] = None) -> Dict[str, Any]: ...

    @abstractmethod
    def delete(self, note_id: str, commit_message: Optional[str] = None) -> Dict[str, Any]: ...

    @abstractmethod
    def list_tags(self) -> Dict[str, Any]: ...

    @abstractmethod
    def list_links(self, note_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def get_properties(self, note_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def set_properties(self, note_id: str, properties: Dict[str, Any]) -> Dict[str, Any]: ...


class ObsidianAdapter(MemoryProvider):
    """Thin adapter: `detect()`/`status()` do real, general capability
    probing (see detect_obsidian_cli()). Every OTHER method returns a clear
    NOT_AVAILABLE result -- intentionally, per the spec's own Phase 8
    design: this codebase has never observed a real obsidian-cli's exact
    command syntax on any machine, so guessing at subprocess invocations
    for search/read/create/update/delete/list_tags/list_links/
    get_properties/set_properties would risk silently fabricating results
    instead of honestly degrading. HybridMemoryProvider (below) is what
    actually gets handed to callers -- it tries this adapter first when
    status() is READY and transparently falls back to
    FileSystemMarkdownAdapter for the same call whenever this adapter
    reports NOT_AVAILABLE (today: always), so the memory system never
    silently loses a write just because a future machine happens to have
    an unwired CLI binary on PATH."""

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_path = Path(vault_path) if vault_path is not None else None
        self._cached_report: Optional[Dict[str, Any]] = None

    def detect(self) -> Dict[str, Any]:
        if self._cached_report is None:
            report = detect_obsidian_cli()
            if self.vault_path is not None:
                try:
                    report["vault_access"] = self.vault_path.exists() and os.access(
                        str(self.vault_path), os.R_OK | os.W_OK)
                except OSError:
                    report["vault_access"] = False
            self._cached_report = report
        return self._cached_report

    def status(self) -> Dict[str, Any]:
        d = self.detect()
        return {"provider": "obsidian_cli", "status": d["status"], "detail": d}

    def _not_available(self) -> Dict[str, Any]:
        d = self.detect()
        if d.get("installed"):
            reason = (f"Obsidian CLI detected ({d.get('executable')}, version {d.get('version')}) "
                      f"but ObsidianAdapter does not wire real operations against it -- its command "
                      f"contract has never been verified against an actual installed instance; "
                      f"extend this adapter's methods once confirmed.")
        else:
            reason = "Obsidian CLI is not installed on this machine."
        return {"ok": False, "status": "NOT_AVAILABLE", "reason": reason, "fallback": "FileSystemMarkdownAdapter"}

    def search(self, query: Dict[str, Any], limit: int = 8) -> Dict[str, Any]: return self._not_available()
    def read(self, note_id: str) -> Dict[str, Any]: return self._not_available()
    def create(self, frontmatter: Dict[str, Any], sections: Optional[Dict[str, str]] = None,
               body: Optional[str] = None, commit_message: Optional[str] = None) -> Dict[str, Any]:
        return self._not_available()
    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None,
               commit_message: Optional[str] = None) -> Dict[str, Any]:
        return self._not_available()
    def delete(self, note_id: str, commit_message: Optional[str] = None) -> Dict[str, Any]:
        return self._not_available()
    def list_tags(self) -> Dict[str, Any]: return self._not_available()
    def list_links(self, note_id: str) -> Dict[str, Any]: return self._not_available()
    def get_properties(self, note_id: str) -> Dict[str, Any]: return self._not_available()
    def set_properties(self, note_id: str, properties: Dict[str, Any]) -> Dict[str, Any]: return self._not_available()


_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


class FileSystemMarkdownAdapter(MemoryProvider):
    """The real, fully-functional MemoryProvider: every method genuinely
    operates on Markdown+YAML-frontmatter files under `vault_path`. No
    embedding/vector index -- search() is real keyword/tag/YAML-property/
    wiki-link-traversal/protocol/project/memory-level/confidence/status
    filtering over an on-demand filesystem scan, optionally accelerated by
    `rg` as a candidate-file prefilter. Every filter still re-parses real
    frontmatter in Python, and `_candidate_paths()` narrows only on terms
    that are mandatory constraints on the result, so a missing/broken `rg`
    changes speed and never results -- see that method for the two rules
    that keep it that way."""

    def __init__(self, vault_path: Path, git_enabled: bool = False):
        self.vault_path = Path(vault_path)
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.git_enabled = bool(git_enabled) and shutil.which("git") is not None
        if self.git_enabled:
            _ensure_git_repo(self.vault_path)

    # -- MemoryProvider interface --

    def detect(self) -> Dict[str, Any]:
        accessible = False
        try:
            self.vault_path.mkdir(parents=True, exist_ok=True)
            probe = self.vault_path / ".dv_harness_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            accessible = True
        except OSError:
            accessible = False
        cap = "READY" if accessible else "NOT_AVAILABLE"
        return {
            "installed": True, "version": "builtin", "executable": None, "vault_access": accessible,
            "search": cap, "read": cap, "create": cap, "update": cap,
            "properties": cap, "tags": cap, "links": cap,
            "status": "READY" if accessible else "BLOCKED",
        }

    def status(self) -> Dict[str, Any]:
        d = self.detect()
        return {"provider": "filesystem_markdown", "status": d["status"], "vault_path": str(self.vault_path),
                "detail": d}

    def search(self, query: Dict[str, Any], limit: int = 8) -> Dict[str, Any]:
        query = query or {}
        text_q = str(query.get("text", "")).strip()
        exact_q = query.get("exact")
        tag_q = query.get("tag")
        linked_to = query.get("linked_to")
        property_filters = dict(query.get("property") or {})
        for f in ("protocol", "project", "memory_level", "confidence", "status"):
            if query.get(f):
                property_filters[f] = query[f]

        structural_filter = bool(tag_q or property_filters or linked_to)
        any_filter = bool(text_q or exact_q or structural_filter)
        candidates = self._candidate_paths(text_q, exact_q,
                                            text_is_mandatory=not structural_filter)
        q_tokens = _tokenize(text_q) if text_q else set()

        scored = []
        for p in candidates:
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, body = parse_note_markdown(text)
            note_id = fm.get("id") or p.stem

            if exact_q and exact_q not in text:
                continue
            if any(str(fm.get(k, "")) != str(v) for k, v in property_filters.items()):
                continue
            if tag_q and tag_q not in (fm.get("tags") or []):
                continue
            if linked_to and linked_to not in _WIKILINK_RE.findall(body):
                continue

            score = 0.0
            score += 3.0 * sum(1 for k in property_filters if str(fm.get(k, "")) == str(property_filters[k]))
            score += 2.0 if tag_q else 0.0
            score += 2.0 if linked_to else 0.0
            score += 2.0 if exact_q else 0.0
            if q_tokens:
                haystack = " ".join(str(v) for v in fm.values() if isinstance(v, (str, int, float))) + " " + body
                score += len(q_tokens & _tokenize(haystack)) * 1.0
            if not any_filter:
                score = 0.1  # an empty query intentionally means "list everything in the vault"
            if score <= 0:
                continue
            scored.append((score, note_id, p, fm))

        scored.sort(key=lambda r: r[0], reverse=True)
        results = [
            {"score": score, "note_id": note_id, "path": str(p.relative_to(self.vault_path)), "frontmatter": fm}
            for score, note_id, p, fm in scored[:limit]
        ]
        return {"ok": True, "results": results}

    def read(self, note_id: str) -> Dict[str, Any]:
        p = self._find_note_path(note_id)
        if p is None:
            return {"ok": False, "error": "NOT_FOUND"}
        fm, body = parse_note_markdown(p.read_text(encoding="utf-8"))
        return {"ok": True, "note_id": note_id, "path": str(p.relative_to(self.vault_path)),
                "frontmatter": fm, "body": body}

    def create(self, frontmatter: Dict[str, Any], sections: Optional[Dict[str, str]] = None,
               body: Optional[str] = None, folder: Optional[str] = None,
               commit_message: Optional[str] = None) -> Dict[str, Any]:
        fm = dict(frontmatter)
        note_id = fm.get("id") or _gen_note_id()
        fm["id"] = note_id
        existing = self._find_note_path(note_id)
        if existing is not None:
            return {"ok": False, "error": "ALREADY_EXISTS", "note_id": note_id,
                    "path": str(existing.relative_to(self.vault_path))}
        fm.setdefault("created", _now_iso())
        fm.setdefault("updated", fm["created"])

        sections_out = sections if sections is not None else (_body_to_sections(body) if body else None)
        # Phase 19 security redaction (Workstream 2, dv_harness/memory_security.py):
        # run BEFORE any content is written to the note -- never as an
        # after-the-fact scrub. Additive: a note with no secret-shaped
        # content in any frontmatter value or section is completely
        # unaffected (only fields where a real pattern actually matched are
        # ever touched), so this never changes output for the pre-existing
        # 41-test Workstream-1 suite.
        from . import memory_security as _msec
        fm, sections_out, secret_findings = _msec.redact_note_content(fm, sections_out)
        if secret_findings:
            fm["secrets_redacted"] = True
            fm["secrets_redacted_types"] = sorted({f["type"] for f in secret_findings})

        validation = validate_note_frontmatter(fm)
        fm["schema_status"] = validation["schema_status"]

        folder_rel = folder or _MEMORY_LEVEL_FOLDER.get(str(fm.get("memory_level") or "").lower(), "00_Inbox")
        target_dir = self.vault_path / folder_rel
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{_sanitize_note_id(note_id)}.md"
        path.write_text(render_note_markdown(fm, sections_out), encoding="utf-8")
        # Phase 13 -- Git Integration: `commit_message` (additive, default
        # None) lets a policy-aware caller (memory_router.py's
        # `_maybe_write_vault_note()`) supply the real
        # `memory(<protocol>): <short description>` commit-message format
        # the user's spec requires; omitting it (every pre-existing direct
        # caller, e.g. this class's own Workstream-1 tests) reproduces the
        # exact prior generic message unchanged.
        commit = self._maybe_git_commit(commit_message or f"memory-vault: create {note_id}")
        result = {"ok": True, "note_id": note_id, "path": str(path.relative_to(self.vault_path)),
                  "validation": validation}
        apply_commit_outcome(result, commit)
        if secret_findings:
            result["secrets_redacted"] = [{"type": f["type"], "field": f["field"]} for f in secret_findings]
        return result

    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None,
               commit_message: Optional[str] = None) -> Dict[str, Any]:
        p = self._find_note_path(note_id)
        if p is None:
            return {"ok": False, "error": "NOT_FOUND"}
        fm, body = parse_note_markdown(p.read_text(encoding="utf-8"))
        sections = _body_to_sections(body)
        if frontmatter_patch:
            fm.update(frontmatter_patch)
        fm["id"] = note_id  # a patch may never silently change a note's own identity
        fm["updated"] = _now_iso()
        if sections_patch:
            sections.update(sections_patch)

        # Phase 19 security redaction -- see create()'s matching comment
        # above. Re-run over the FULL merged frontmatter/sections (not just
        # the incoming patch) on every update, so a secret introduced via
        # any single patch can never survive on disk past that write.
        from . import memory_security as _msec
        fm, sections, secret_findings = _msec.redact_note_content(fm, sections)
        if secret_findings:
            fm["secrets_redacted"] = True
            fm["secrets_redacted_types"] = sorted({f["type"] for f in secret_findings})

        validation = validate_note_frontmatter(fm)
        fm["schema_status"] = validation["schema_status"]
        p.write_text(render_note_markdown(fm, sections), encoding="utf-8")
        commit = self._maybe_git_commit(commit_message or f"memory-vault: update {note_id}")
        result = {"ok": True, "note_id": note_id, "path": str(p.relative_to(self.vault_path)), "validation": validation}
        apply_commit_outcome(result, commit)
        if secret_findings:
            result["secrets_redacted"] = [{"type": f["type"], "field": f["field"]} for f in secret_findings]
        return result

    def delete(self, note_id: str, commit_message: Optional[str] = None) -> Dict[str, Any]:
        p = self._find_note_path(note_id)
        if p is None:
            return {"ok": False, "error": "NOT_FOUND"}
        p.unlink()
        commit = self._maybe_git_commit(commit_message or f"memory-vault: delete {note_id}")
        result = {"ok": True, "note_id": note_id}
        apply_commit_outcome(result, commit)
        return result

    def list_tags(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for p in self._iter_notes():
            try:
                fm, _ = parse_note_markdown(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            for t in fm.get("tags") or []:
                counts[t] = counts.get(t, 0) + 1
        return {"ok": True, "tags": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))}

    def list_links(self, note_id: str) -> Dict[str, Any]:
        r = self.read(note_id)
        if not r.get("ok"):
            return r
        forward = sorted(set(_WIKILINK_RE.findall(r["body"])))
        this_path = self._find_note_path(note_id)
        backlinks = set()
        for p in self._iter_notes():
            if p == this_path:
                continue
            try:
                fm2, body2 = parse_note_markdown(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            if note_id in _WIKILINK_RE.findall(body2):
                backlinks.add(fm2.get("id") or p.stem)
        return {"ok": True, "note_id": note_id, "forward_links": forward, "backlinks": sorted(backlinks)}

    def get_properties(self, note_id: str) -> Dict[str, Any]:
        r = self.read(note_id)
        if not r.get("ok"):
            return r
        return {"ok": True, "note_id": note_id, "properties": r["frontmatter"]}

    def set_properties(self, note_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        r = self.update(note_id, frontmatter_patch=properties)
        if not r.get("ok"):
            return r
        return self.get_properties(note_id)

    # -- internals --

    def _iter_notes(self) -> List[Path]:
        if not self.vault_path.exists():
            return []
        return [p for p in self.vault_path.rglob("*.md") if ".git" not in p.parts]

    def _find_note_path(self, note_id: str) -> Optional[Path]:
        sanitized = _sanitize_note_id(note_id)
        for p in self._iter_notes():
            if p.stem == sanitized:
                return p
        for p in self._iter_notes():  # fallback: a hand-renamed file, matched by frontmatter id
            try:
                fm, _ = parse_note_markdown(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            if fm.get("id") == note_id:
                return p
        return None

    def _candidate_paths(self, text_q: str, exact_q: Optional[str] = None,
                          text_is_mandatory: bool = True) -> List[Path]:
        """Optional `rg -l` prefilter narrowing which note files search()
        parses. It is only ever allowed to be a SPEED optimization, so it may
        narrow on a term only while that term is a MANDATORY constraint on the
        final result -- otherwise `rg` being installed would silently change
        what a search means, which is not an optimization but a second,
        undeclared filter. Two rules follow, and both were real divergences:

        `exact` is a hard `continue` in search() and is always mandatory, so
        it prefilters unconditionally; `rg -i` makes the prefilter deliberately
        over-inclusive against search()'s case-SENSITIVE check, which is the
        safe direction (Python still rejects, rg never over-prunes).

        Free text is scored by TOKEN OVERLAP, so its prefilter must be the
        UNION of its tokens (one `-F -e` each), never the whole query as one
        contiguous literal phrase -- and it is mandatory only when no
        structural filter accompanies it, because a note matching a
        tag/property/wiki-link filter alone still clears search()'s relevance
        floor and must be returned whether or not it contains any query token.
        """
        if exact_q:
            patterns = [str(exact_q)]
        elif text_is_mandatory:
            patterns = sorted(_tokenize(text_q))
        else:
            patterns = []
        if not patterns:
            return self._iter_notes()
        rg = shutil.which("rg")
        if not rg:
            return self._iter_notes()
        cmd = [rg, "-l", "-i", "-F", "--glob", "*.md"]
        for pattern in patterns:
            cmd += ["-e", pattern]
        cmd.append(str(self.vault_path))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode not in (0, 1):  # 1 == "ran fine, zero matches"
                return self._iter_notes()
            return [Path(line) for line in proc.stdout.splitlines() if line.strip()]
        except Exception:  # pragma: no cover - rg must never be a hard dependency for correctness
            return self._iter_notes()

    def _maybe_git_commit(self, message: str) -> Dict[str, Any]:
        """The full `_commit_vault_change_detailed()` outcome, or an empty
        dict when git integration is off -- `apply_commit_outcome()` turns
        either into result-dict keys."""
        if self.git_enabled:
            return _commit_vault_change_detailed(self.vault_path, message)
        return {}


def _sanitize_note_id(note_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(note_id))


class HybridMemoryProvider(MemoryProvider):
    """What real callers (memory_router.py's vault write-through, and the
    future Memory Agent) actually hold: composes ObsidianAdapter +
    FileSystemMarkdownAdapter and, PER CALL, tries Obsidian first only when
    its own status() currently reports READY, falling back to the
    filesystem adapter whenever that specific call itself comes back
    NOT_AVAILABLE (today, always -- see ObsidianAdapter's docstring) or
    Obsidian was never READY to begin with. This is deliberately a per-call
    decision, not a one-time provider pick at construction time: an
    all-or-nothing pick keyed only on ObsidianAdapter.status() would silently
    stop writing anything real the moment a future machine's status() ever
    reports READY, since this thin adapter's operations stay NOT_AVAILABLE
    regardless of installation until a future revision genuinely wires
    them against a confirmed CLI contract."""

    def __init__(self, obsidian: ObsidianAdapter, filesystem: FileSystemMarkdownAdapter):
        self.obsidian = obsidian
        self.filesystem = filesystem

    def _dispatch(self, method_name: str, *args, **kwargs) -> Dict[str, Any]:
        if self.obsidian.status().get("status") == "READY":
            result = getattr(self.obsidian, method_name)(*args, **kwargs)
            if result.get("status") != "NOT_AVAILABLE":
                return result
        return getattr(self.filesystem, method_name)(*args, **kwargs)

    def detect(self) -> Dict[str, Any]:
        return self.obsidian.detect()

    def status(self) -> Dict[str, Any]:
        obs, fs = self.obsidian.status(), self.filesystem.status()
        return {"provider": "hybrid", "status": fs.get("status", "PARTIAL"), "obsidian": obs, "filesystem": fs}

    def search(self, query: Dict[str, Any], limit: int = 8) -> Dict[str, Any]:
        return self._dispatch("search", query, limit)

    def read(self, note_id: str) -> Dict[str, Any]:
        return self._dispatch("read", note_id)

    def create(self, frontmatter: Dict[str, Any], sections: Optional[Dict[str, str]] = None,
               body: Optional[str] = None, commit_message: Optional[str] = None) -> Dict[str, Any]:
        return self._dispatch("create", frontmatter, sections, body, commit_message=commit_message)

    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None,
               commit_message: Optional[str] = None) -> Dict[str, Any]:
        return self._dispatch("update", note_id, frontmatter_patch, sections_patch, commit_message=commit_message)

    def delete(self, note_id: str, commit_message: Optional[str] = None) -> Dict[str, Any]:
        return self._dispatch("delete", note_id, commit_message=commit_message)

    def list_tags(self) -> Dict[str, Any]:
        return self._dispatch("list_tags")

    def list_links(self, note_id: str) -> Dict[str, Any]:
        return self._dispatch("list_links", note_id)

    def get_properties(self, note_id: str) -> Dict[str, Any]:
        return self._dispatch("get_properties", note_id)

    def set_properties(self, note_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        return self._dispatch("set_properties", note_id, properties)


def get_active_provider(project_root: Path, cfg: Optional[Dict[str, Any]] = None) -> MemoryProvider:
    """Factory every real caller should use instead of constructing an
    adapter directly. Bootstraps the vault on first use (Phase 3), then
    returns HybridMemoryProvider unless `memory.obsidian_cli` is explicitly
    "disabled" in config (in which case Obsidian is not even probed --
    an explicit opt-out, distinct from "auto", which always probes but
    still safely degrades)."""
    if cfg is None:
        from .config import load_config
        cfg = load_config(project_root)
    memory_cfg = cfg.get("memory") or {}
    vault_path = resolve_vault_path(project_root, cfg)
    bootstrap_vault(vault_path)
    # False when a caller's own cfg dict omits "memory" entirely (e.g. a
    # hand-built partial cfg that never went through config.load_config()'s
    # DEFAULT_CONFIG merge) -- matches DEFAULT_CONFIG's own git_enabled
    # default; see config.py's memory.git_enabled comment for why this is
    # opt-in, not opt-out.
    git_enabled = bool(memory_cfg.get("git_enabled", False))
    fs = FileSystemMarkdownAdapter(vault_path, git_enabled=git_enabled)
    if str(memory_cfg.get("obsidian_cli", "auto")).lower() == "disabled":
        return fs
    return HybridMemoryProvider(ObsidianAdapter(vault_path=vault_path), fs)


# ---------------------------------------------------------------------------
# Record -> Note mapping (used by memory_router.py's promotion write-through)
# ---------------------------------------------------------------------------

# Destination -> Phase-7 memory_level (Phase 13 -- Git Integration,
# 2026-09-03 extension): originally this function only ever distinguished
# ENGINEERING_MEMORY from "everything else is organizational", correct back
# when the router's vault write-through only ever called it for those two
# destinations. Now that JOB_MEMORY/PROJECT_MEMORY also write through (see
# memory_router._VAULT_WRITE_THROUGH_DESTINATIONS), each destination needs
# its own real memory_level so the note lands in the right VAULT_STRUCTURE
# folder (_MEMORY_LEVEL_FOLDER) instead of every job/project note being
# mislabeled "organizational".
_DESTINATION_TO_MEMORY_LEVEL = {
    "JOB_MEMORY": "job",
    "PROJECT_MEMORY": "project",
    "ENGINEERING_MEMORY": "engineering",
    "ORGANIZATIONAL_MEMORY": "organizational",
}


def build_frontmatter_from_memory_record(destination: str, mem: Dict[str, Any],
                                          project_name: Optional[str] = None) -> Dict[str, Any]:
    """Maps a MemoryStore/OrganizationalMemoryStore record onto the Phase 7
    note schema. Fields the record simply doesn't carry (rtl_sha, tb_sha,
    vip_vendor, ...) are emitted as null rather than omitted, so the note's
    own frontmatter always shows the full schema shape.

    `protocol` is the one exception, because it is a REQUIRED field: a
    record with no protocol gets GENERAL_PROTOCOL, the same honest
    "not protocol-specific" key the rest of this write path already uses
    for that record -- see that constant's own comment."""
    level = _DESTINATION_TO_MEMORY_LEVEL.get(destination, "organizational")
    created = mem.get("created_at")
    created_iso = _epoch_to_iso(created) if isinstance(created, (int, float)) else (created or _now_iso())
    # Tags stay derived from the record's OWN protocol, never from the
    # GENERAL_PROTOCOL fallback: "_general" as a tag on every non-protocol
    # note carries no information a reader could filter on, while the
    # `protocol` field's own value is exactly what makes those notes
    # reachable by `--protocol _general`.
    tags = sorted({str(v).lower().replace(" ", "-") for v in
                   (mem.get("protocol"), mem.get("scope"), level, mem.get("confidence")) if v})
    last_confirmed = mem.get("last_confirmed_at")
    return {
        "id": mem.get("memory_id") or mem.get("ccl_id") or _gen_note_id(),
        "memory_level": level,
        "protocol": mem.get("protocol") or GENERAL_PROTOCOL,
        "subsystem": mem.get("scope"),
        "category": mem.get("category") or mem.get("scope"),
        "failure": str(mem.get("title") or mem.get("root_cause") or "untitled")[:200],
        "status": mem.get("status", "ACTIVE"),
        "confidence": mem.get("confidence", "UNKNOWN"),
        "project": mem.get("project") or project_name,
        "rtl_sha": mem.get("rtl_sha"),
        "tb_sha": mem.get("tb_sha"),
        "vip_vendor": mem.get("vip_vendor"),
        "vip_version": mem.get("vip_version"),
        "simulator": mem.get("simulator"),
        "created": created_iso,
        "updated": _now_iso(),
        "tags": tags,
        "confirmation_count": mem.get("confirmation_count", 0),
        "last_confirmed_at": _epoch_to_iso(last_confirmed) if isinstance(last_confirmed, (int, float)) else None,
        # Phase 13 traceability: carried through when the underlying record
        # already has one (e.g. a re-render of a record memory_router.py
        # previously wrote back a knowledge_commit_sha onto) -- see
        # MEMORY_NOTE_OPTIONAL_FIELDS' own comment above for why this is
        # never set by re-committing the note itself.
        "knowledge_commit_sha": mem.get("knowledge_commit_sha"),
    }


def _format_dict_or_list(value: Any) -> str:
    if not value:
        return "_Not captured._"
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return "\n".join(f"- **{k}**: {v}" for k, v in value.items())
    return str(value)


def build_sections_from_memory_record(mem: Dict[str, Any]) -> Dict[str, str]:
    """Phase 7's body-section content, including real `[[WikiLink]]` entries
    in "Related Knowledge" back to whichever finding/prior-memory this
    record was derived from (the only stable cross-references this record
    reliably carries)."""
    related = []
    if mem.get("source_finding_id"):
        related.append(f"[[{mem['source_finding_id']}]]")
    if mem.get("source_engineering_memory_id"):
        related.append(f"[[{mem['source_engineering_memory_id']}]]")
    return {
        "Symptom": _format_dict_or_list(mem.get("symptoms")),
        "Context": str(mem.get("scope") or "_Not captured._"),
        "Hypothesis": str(mem.get("hypothesis") or "_Not captured (see Root Cause)._"),
        "Evidence": _format_dict_or_list(mem.get("evidence")),
        "Root Cause": str(mem.get("root_cause") or "_Not captured._"),
        "Fix": str(mem.get("fix") or "_Not captured._"),
        "Verification": _format_dict_or_list(mem.get("verification")),
        "Confidence": str(mem.get("confidence", "UNKNOWN")),
        "Reusability": "Reusable" if mem.get("reusable") else "Not yet assessed",
        "Known Limitations": str(mem.get("known_limitations") or "_None documented._"),
        "Related Knowledge": "\n".join(f"- {r}" for r in related) if related else "_None linked yet._",
    }


_MEMORY_LEVEL_TO_DESTINATION = {level: dest for dest, level in _DESTINATION_TO_MEMORY_LEVEL.items()}


def _project_name_from_disk(project_root: Path) -> Optional[str]:
    """Same `.dv-harness/project.json` lookup memory_router._maybe_write_vault_note()
    does before building a note's frontmatter, so a re-render produces the
    same `project` value the original write did rather than dropping it."""
    try:
        import json as _json
        project_json = Path(project_root) / ".dv-harness" / "project.json"
        if project_json.exists():
            return (_json.loads(project_json.read_text(encoding="utf-8")) or {}).get("project")
    except Exception:
        pass
    return None


def resync_notes_from_memory_store(project_root: Path, cfg: Optional[Dict[str, Any]] = None,
                                    note_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Re-render vault notes from the durable MemoryStore records they mirror
    (`dv-harness memory resync-notes`).

    A Memory Note is a mirror; the per-tier JSON record under
    `.dv-harness/memory/<level>/` is the system of record. So a note written
    by an older/buggier version of build_frontmatter_from_memory_record()
    stays wrong on disk forever even after the mapper is fixed -- nothing
    re-derives it, because the router only writes a note when the underlying
    record is written or updated. That is a real, measured state, not a
    hypothetical: this project's own 9 vault notes were all schema_status
    PARTIAL on `protocol` (see GENERAL_PROTOCOL's comment) with 9 perfectly
    healthy source records sitting beside them. This is the repair, in the
    same spirit as MemoryStore.reindex() repairing index.json from the record
    files that are the truth behind it.

    It NEVER invents content: every field comes from the source record via
    the same build_frontmatter_from_memory_record()/
    build_sections_from_memory_record() pair the real write path uses. A note
    whose record is gone, or whose `memory_level` names no known tier, is
    reported in `skipped` with its reason and left byte-for-byte untouched --
    a mirror with nothing left to mirror is a fact to surface, not a note to
    rewrite from guesses.
    """
    from .memory import MemoryStore

    vault_path = resolve_vault_path(project_root, cfg)
    provider = get_active_provider(project_root, cfg)
    store = MemoryStore(Path(project_root))
    project_name = _project_name_from_disk(project_root)
    notes_root = vault_path / "06_Agent_Memory"
    wanted = set(note_ids) if note_ids else None

    resynced: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for path in sorted(notes_root.rglob("*.md")) if notes_root.exists() else []:
        if ".git" in path.parts:
            continue
        frontmatter, body = parse_note_markdown(path.read_text(encoding="utf-8"))
        note_id = frontmatter.get("id") or path.stem
        if wanted is not None and note_id not in wanted:
            continue
        entry = {"note_id": note_id, "path": str(path.relative_to(vault_path)),
                 "before": validate_note(frontmatter, body)["note_status"]}
        destination = _MEMORY_LEVEL_TO_DESTINATION.get(str(frontmatter.get("memory_level") or "").lower())
        if destination is None:
            skipped.append({**entry, "reason": "UNKNOWN_MEMORY_LEVEL",
                            "memory_level": frontmatter.get("memory_level")})
            continue
        record = store.get(note_id)
        if not record:
            skipped.append({**entry, "reason": "NO_SOURCE_RECORD"})
            continue
        result = provider.update(
            note_id,
            frontmatter_patch=build_frontmatter_from_memory_record(destination, record,
                                                                    project_name=project_name),
            sections_patch=build_sections_from_memory_record(record),
            # One commit-message policy for this vault, not two: reuse the
            # router's own `memory(<protocol>): ...` builder rather than
            # re-deriving the format here. Imported lazily because
            # memory_router imports THIS module the same way.
            commit_message=_resync_commit_message(record, note_id),
        )
        if not result.get("ok"):
            skipped.append({**entry, "reason": result.get("error") or "UPDATE_FAILED"})
            continue
        fm_after, body_after = parse_note_markdown(
            (vault_path / result["path"]).read_text(encoding="utf-8"))
        resynced.append({**entry, "after": validate_note(fm_after, body_after)["note_status"]})

    still_partial = [e["note_id"] for e in resynced if e["after"] != "COMPLETE"]
    return {"ok": True, "vault_path": str(vault_path), "resynced": resynced, "skipped": skipped,
            "repaired": [e["note_id"] for e in resynced if e["before"] != "COMPLETE" and e["after"] == "COMPLETE"],
            "still_partial": still_partial}


def _resync_commit_message(record: Dict[str, Any], note_id: str) -> str:
    from .memory_router import _build_vault_commit_message
    return _build_vault_commit_message({**record, "title": f"resync note {note_id} from its MemoryStore record"})


# ---------------------------------------------------------------------------
# Phase 10/11 (Workstream 3, 2026-09-03): shared failure-signature capture +
# prior-knowledge search interface. This is the ONE minimal, real entry point
# that BOTH the debug flow (engine.py's DVHarness.run_stage(), FAILURE_RECOVERY
# stage -- "before a debug attempt") and the regression-job memory extraction
# (lsf_client.py's `_write_job_tier_memory_on_terminal_reconcile`, on a real
# UVM_ERROR/UVM_FATAL/abnormal-termination signal) call, and the exact minimal
# signature the future Memory Agent (`.claude/agents/memory-agent.md`, Phase
# 17, a separate workstream not built here) should call rather than
# reimplementing a third search path of its own.
#
# Per CLAUDE.md's Evidence Truth Rule / Core Operating Rule "Memory is prior
# knowledge, not current evidence" / "不得直接假設 previous root cause == current
# root cause": every caller of `search_related_memory_for_debug()` below must
# treat its `related_cases` as CANDIDATES to independently re-verify against
# CURRENT RTL/VIP/log/waveform evidence -- this module never claims a match
# IS the answer, and neither function here ever writes anything; they are
# read-only prior-knowledge lookups.
# ---------------------------------------------------------------------------

def build_failure_signature(*, protocol: Optional[str] = None, pattern: Optional[str] = None,
                             symptom: Optional[str] = None, root_cause_hint: Optional[str] = None,
                             uvm_error_count: int = 0, uvm_fatal_count: int = 0,
                             assertion_failure: bool = False, simulator_crash: bool = False,
                             terminal_signature: Optional[str] = None, lsf_status: Optional[str] = None,
                             extra_text: Optional[str] = None,
                             vip_agent: Optional[str] = None,
                             resource: Optional[str] = None) -> Dict[str, Any]:
    """Canonical "what does this failure look like" fact (Phase 10/11): the
    ONE structured shape every real caller builds identically, so
    `search_related_memory_for_debug()` below has one stable input rather
    than each caller inventing its own query dict. Every field is optional
    and never guessed -- a caller supplies exactly the real evidence it has:
    engine.py sources protocol/symptom/root_cause_hint from the Blackboard
    "findings" topic's last_report and route_info["protocol_decision"];
    lsf_client.py sources uvm_error_count/uvm_fatal_count/assertion_failure/
    simulator_crash/terminal_signature/lsf_status directly from the real
    JobState fields `evaluate_auto_kill()` already reads for the exact same
    UVM_ERROR/UVM_FATAL/abnormal-termination signal.

    `abnormal_termination` is derived here (never asked of the caller) from
    exactly the same real-evidence fields `evaluate_auto_kill()`'s
    kill_on_uvm_fatal/kill_on_fatal_assertion/kill_on_simulator_crash
    triggers already treat as terminal, plus a live EXIT status or any
    terminal_signature marker -- one true/false fact, not a second
    definition of "abnormal" for this module to drift from that one.

    `vip_agent` / `resource` (2026-09-05, SYS-31) are OPTIONAL and are OMITTED
    from the returned dict when not supplied -- deliberately, and this is the
    one design detail worth stating here rather than in a commit message.
    `evidence_db.signature_key()` hashes the WHOLE dict
    (`json.dumps(..., sort_keys=True)`), so a key that were always present
    would change every signature this repo has ever computed and orphan the
    accumulated `occurrence_count`/`first_seen`/`last_seen` history on the
    `failure_signatures` table -- silently, since nothing would error. Omitted
    when absent, a caller that supplies neither gets a byte-identical dict and
    an identical key, while a caller that DOES name a VIP agent gets a
    genuinely different signature, which is correct: the same UVM_ERROR from
    two different agents is two failure shapes, not one. This follows the same
    convention `lsf_client.py`'s job record already uses ("a key is OMITTED
    when its source genuinely captured nothing, never written as a null
    placeholder that would look like the schema captured this data when it did
    not")."""
    abnormal_termination = bool(
        uvm_fatal_count > 0 or assertion_failure or simulator_crash
        or lsf_status == "EXIT" or bool(terminal_signature)
    )
    signature = {
        "protocol": protocol, "pattern": pattern, "symptom": symptom,
        "root_cause_hint": root_cause_hint, "uvm_error_count": uvm_error_count,
        "uvm_fatal_count": uvm_fatal_count, "assertion_failure": assertion_failure,
        "simulator_crash": simulator_crash, "terminal_signature": terminal_signature,
        "lsf_status": lsf_status, "abnormal_termination": abnormal_termination,
        "extra_text": extra_text,
    }
    if vip_agent:
        signature["vip_agent"] = vip_agent
    if resource:
        signature["resource"] = resource
    return signature


_EVIDENCE_DB_SIGNATURE_COLUMNS = [
    "signature_key", "protocol", "pattern", "symptom", "root_cause_hint",
    "uvm_error_count", "uvm_fatal_count", "assertion_failure", "simulator_crash",
    "terminal_signature", "lsf_status", "abnormal_termination", "extra_text",
    "occurrence_count", "first_seen", "last_seen", "sample_job_id", "sample_memory_id",
]


def search_evidence_db_failure_signatures(root: Path, failure_signature: Dict[str, Any],
                                           limit: int = 5) -> Dict[str, Any]:
    """Knowledge Layer -> Evidence Layer DuckDB READ edge (2026-09-04).

    THE GAP THIS CLOSES: `evidence_db.py`'s `failure_signatures` table is
    written exclusively from the Execution/Evidence side --
    `EvidenceStore.insert_job_memory_record()` upserts one row per distinct
    failure SHAPE (see `evidence_db.signature_key()`), fed by
    `lsf_client.py`/`regression_reporter.py` from real JobState/sim.log
    evidence. Nothing on the Knowledge side ever read it back: before this
    function, `memory_vault.py`/`memory_router.py` contained no reference to
    `evidence_db` or `duckdb` in either direction, so the accumulated
    `occurrence_count`/`first_seen`/`last_seen` history of "we have hit this
    exact failure shape N times before" was invisible to every debug-time
    prior-evidence lookup. `search_related_memory_for_debug()` below now
    merges these rows with the vault's own Markdown notes.

    READ-ONLY BY CONSTRUCTION: opens `EvidenceStore(..., read_only=True)`, so
    (per that class's own docstring) no mkdir happens, no schema DDL is
    issued, and DuckDB's own read-only connection refuses any write at the
    engine level. This function must never be able to create or migrate the
    evidence database -- a Knowledge-Layer prior-evidence lookup is not a
    reason for a database to spring into existence.

    Ranking deliberately mirrors `FileSystemMarkdownAdapter.search()`'s own
    scoring rather than inventing a second, divergent notion of relevance:
    `protocol` is a hard filter worth 3.0 when supplied (the vault treats it
    as a `property_filters` entry, same weight), and each shared query token
    adds 1.0 via the SAME `_tokenize` this module already imports from
    `memory.py`. That is why the merged list in
    `search_related_memory_for_debug()` can be sorted on one common `score`.

    Best-effort and silent about absence: no evidence database yet (this
    project's `.dv-harness/evidence/evidence.duckdb` genuinely does not exist
    until a first reconciliation cycle runs), no `duckdb` package installed,
    or a locked/corrupt file all return `{"ok": False, "reason": ...,
    "results": []}` -- never a raise, and never a fabricated row. A missing
    evidence DB is a normal state, not an error a debug attempt should feel."""
    results: List[Dict[str, Any]] = []
    try:
        from . import evidence_db as _evdb
    except Exception as exc:  # pragma: no cover - import of a sibling module
        return {"ok": False, "reason": "EVIDENCE_DB_IMPORT_FAILED", "detail": str(exc), "results": results}

    db_path = _evdb.default_db_path(Path(root))
    if not db_path.exists():
        return {"ok": False, "reason": "EVIDENCE_DB_NOT_PRESENT", "db_path": str(db_path), "results": results}

    protocol = failure_signature.get("protocol")
    q_tokens = _tokenize(" ".join(str(v) for v in (
        failure_signature.get("symptom"), failure_signature.get("root_cause_hint"),
        failure_signature.get("terminal_signature"), failure_signature.get("extra_text"),
    ) if v))

    cols = ", ".join(_EVIDENCE_DB_SIGNATURE_COLUMNS)
    sql = f"SELECT {cols} FROM failure_signatures"
    params: List[Any] = []
    if protocol:
        sql += " WHERE protocol = ?"
        params.append(str(protocol))

    try:
        store = _evdb.EvidenceStore(db_path, read_only=True)
    except Exception as exc:
        # duckdb raises IOException for a missing/locked file and
        # CatalogException for a database predating this table -- all of
        # which mean "no prior evidence available here", not a debug failure.
        return {"ok": False, "reason": "EVIDENCE_DB_UNAVAILABLE", "detail": str(exc),
                "db_path": str(db_path), "results": results}
    try:
        rows = store.query(sql, params)
    except Exception as exc:
        return {"ok": False, "reason": "EVIDENCE_DB_QUERY_FAILED", "detail": str(exc),
                "db_path": str(db_path), "results": results}
    finally:
        try:
            store.close()
        except Exception:  # pragma: no cover - closing a read-only handle
            pass

    for row in rows:
        record = dict(zip(_EVIDENCE_DB_SIGNATURE_COLUMNS, row))
        score = 3.0 if protocol else 0.0
        if q_tokens:
            haystack = " ".join(str(record.get(k) or "") for k in
                                ("protocol", "pattern", "symptom", "root_cause_hint",
                                 "terminal_signature", "extra_text"))
            score += float(len(q_tokens & _tokenize(haystack)))
        if score <= 0:
            continue
        # DuckDB hands back real datetime objects for first_seen/last_seen;
        # every consumer of `related_cases` (lsf_client's job-memory record,
        # prompts.py's stage prompt) JSON-serialises it, so stringify here
        # rather than leaking a non-serialisable value into a memory record.
        for ts in ("first_seen", "last_seen"):
            if record.get(ts) is not None and not isinstance(record[ts], str):
                record[ts] = str(record[ts])
        record["score"] = score
        record["source"] = "evidence_db"
        results.append(record)

    results.sort(key=lambda r: (-r["score"], -(r.get("occurrence_count") or 0),
                                str(r.get("signature_key") or "")))
    return {"ok": True, "db_path": str(db_path), "results": results[:limit]}


def search_related_memory_for_debug(root: Path, cfg: Optional[Dict[str, Any]],
                                     failure_signature: Dict[str, Any], limit: int = 5) -> Dict[str, Any]:
    """THE shared Memory Agent interface (Phase 10 debug-flow prior-evidence
    surfacing / Phase 11 regression-job memory extraction): given a
    `failure_signature` (see `build_failure_signature()` above), searches the
    Workstream-1 DV-Knowledge Vault (`HybridMemoryProvider`, via
    `get_active_provider()`) for related prior cases and returns them RANKED
    by the provider's own real `search()` scoring (`FileSystemMarkdownAdapter
    .search()` -- protocol/property match + text-token overlap, see its own
    docstring) -- never an assumed root cause; `related_cases` is prior
    evidence ONLY.

    TWO SOURCES, ONE RANKED LIST (2026-09-04): `related_cases` merges the
    vault's Markdown notes with matching `failure_signatures` rows read out
    of the Evidence Layer's DuckDB store (`search_evidence_db_failure_
    signatures()` above -- read-only, best-effort, silent when no evidence
    database exists yet). Every entry carries a `source` of `"vault"` or
    `"evidence_db"` so a caller can always tell which store a case came from,
    and both are scored on the same scale so one `score`-descending sort is
    meaningful across them. `vault_count`/`evidence_db_count` report the
    split, and `evidence_db` carries that read's own ok/reason so "the
    evidence DB had nothing" and "there is no evidence DB" stay
    distinguishable rather than both looking like an empty result.

    Real callers today: `engine.py`'s `DVHarness.run_stage()` (FAILURE_RECOVERY,
    the actual debug-attempt entry point -- folded into the stage prompt as
    prior evidence, disclaimed exactly like `relevant_memory`/
    `kc_search_results`, see `prompts.build_stage_prompt`'s `vault_related_cases`
    kwarg) and `lsf_client.py`'s `_upsert_job_tier_memory_record()` (called
    from both `_write_job_tier_memory_on_terminal_reconcile()` -- the first,
    coarser bjobs-only reconcile point -- and a second time from
    `regression_reporter.run_reconciliation_cycle()` once a real sim.log
    epilogue parse gives better evidence; see that function's own "THE GAP
    THIS CLOSES" docstring). Either call attaches `related_cases` onto the
    job_failure record it already writes on a real UVM_ERROR/UVM_FATAL/
    abnormal-termination signal, so the Debug Agent that later picks the job
    up has it without a second search. `.claude/agents/memory-agent.md`
    (built by Workstream 4 during this same session) is a separate,
    LLM-dispatched search path (via `memory_cli.py` subcommands) rather than
    a caller of this exact function -- see this workstream's own report for
    how the two relate.

    An empty query (no symptom/root_cause_hint/terminal_signature/protocol at
    all -- a caller with genuinely no real signal yet) deliberately returns no
    results rather than the vault's own "empty query lists everything" search
    convention: an unscoped "list everything" is not useful prior evidence for
    a specific failure, it would just be noise.

    Best-effort: any provider failure (missing vault, unreadable note, etc.)
    returns `{"ok": False, ...}` rather than raising -- a memory-search
    problem must never block a real debug attempt or a real job-memory
    write."""
    try:
        query_text = " ".join(str(v) for v in (
            failure_signature.get("symptom"), failure_signature.get("root_cause_hint"),
            failure_signature.get("terminal_signature"), failure_signature.get("extra_text"),
        ) if v).strip()[:500]
        protocol = failure_signature.get("protocol")
        if not query_text and not protocol:
            return {"ok": True, "failure_signature": failure_signature, "related_cases": [], "count": 0}
        provider = get_active_provider(root, cfg)
        query: Dict[str, Any] = {}
        if query_text:
            query["text"] = query_text
        if protocol:
            query["protocol"] = protocol
        result = provider.search(query, limit=limit)
        vault_ok = bool(result.get("ok"))
        vault_cases = [{**r, "source": "vault"} for r in ((result.get("results") or []) if vault_ok else [])]

        evidence = search_evidence_db_failure_signatures(root, failure_signature, limit=limit)
        evidence_cases = evidence.get("results") or []

        related = sorted(vault_cases + evidence_cases,
                         key=lambda c: -float(c.get("score") or 0.0))
        return {"ok": vault_ok or bool(evidence.get("ok")), "failure_signature": failure_signature,
                "related_cases": related, "count": len(related),
                "vault_count": len(vault_cases), "evidence_db_count": len(evidence_cases),
                "evidence_db": {k: v for k, v in evidence.items() if k != "results"}}
    except Exception as exc:  # pragma: no cover - a memory search failure must never break a debug attempt
        return {"ok": False, "error": "MEMORY_SEARCH_FAILED", "detail": str(exc),
                "failure_signature": failure_signature, "related_cases": [], "count": 0}
