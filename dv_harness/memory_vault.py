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
    `MEMORY_NOTE_OPTIONAL_FIELDS` / `MEMORY_NOTE_BODY_SECTIONS`,
    `validate_note_frontmatter()`, `render_note_markdown()` /
    `parse_note_markdown()`. A note missing a required field is written with
    `schema_status: PARTIAL` baked into its own frontmatter -- never
    silently written as if it were complete.

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
# "status" and "confidence" are required because a memory note that cannot
# say WHICH protocol, whether it is still trusted, or how confident it is,
# is not yet reusable knowledge -- exactly the bar CLAUDE.md's "memory is
# prior knowledge, not current evidence" already sets for anything read back
# out of Memory.
MEMORY_NOTE_REQUIRED_FIELDS = ["id", "memory_level", "protocol", "status", "confidence", "created", "updated"]

# Optional -- present when the originating record/caller has them, never
# required for a note to be written, but always emitted (as null) so a
# reader/Obsidian's own Properties view sees the full schema shape even on a
# sparse note.
MEMORY_NOTE_OPTIONAL_FIELDS = [
    "subsystem", "category", "failure", "project", "rtl_sha", "tb_sha",
    "vip_vendor", "vip_version", "simulator", "tags",
]

MEMORY_NOTE_ALL_FIELDS = MEMORY_NOTE_REQUIRED_FIELDS + MEMORY_NOTE_OPTIONAL_FIELDS

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
    merely returned once and forgotten."""
    missing = [f for f in MEMORY_NOTE_REQUIRED_FIELDS if frontmatter.get(f) in (None, "")]
    return {"schema_status": "PARTIAL" if missing else "COMPLETE", "missing_required": missing}


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

def _run_git(vault_path: Path, args: List[str], timeout: int = 10) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(["git"] + args, cwd=str(vault_path), capture_output=True, text=True, timeout=timeout)
    except Exception:  # pragma: no cover - git invocation must never break a memory write
        return None


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


def _commit_vault_change(vault_path: Path, message: str) -> bool:
    _run_git(vault_path, ["add", "-A"])
    r = _run_git(vault_path, ["commit", "-m", message])
    return r is not None and r.returncode == 0


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
               body: Optional[str] = None) -> Dict[str, Any]: ...

    @abstractmethod
    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None) -> Dict[str, Any]: ...

    @abstractmethod
    def delete(self, note_id: str) -> Dict[str, Any]: ...

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
               body: Optional[str] = None) -> Dict[str, Any]: return self._not_available()
    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None) -> Dict[str, Any]: return self._not_available()
    def delete(self, note_id: str) -> Dict[str, Any]: return self._not_available()
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
    `rg` (used only as a candidate-file prefilter; every structural filter
    still re-parses real frontmatter in Python, so a missing/broken `rg`
    never changes correctness, only speed)."""

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

        candidates = self._candidate_paths(text_q or (exact_q or ""))
        q_tokens = _tokenize(text_q) if text_q else set()
        any_filter = bool(text_q or exact_q or tag_q or property_filters or linked_to)

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
               body: Optional[str] = None, folder: Optional[str] = None) -> Dict[str, Any]:
        fm = dict(frontmatter)
        note_id = fm.get("id") or _gen_note_id()
        fm["id"] = note_id
        existing = self._find_note_path(note_id)
        if existing is not None:
            return {"ok": False, "error": "ALREADY_EXISTS", "note_id": note_id,
                    "path": str(existing.relative_to(self.vault_path))}
        fm.setdefault("created", _now_iso())
        fm.setdefault("updated", fm["created"])
        validation = validate_note_frontmatter(fm)
        fm["schema_status"] = validation["schema_status"]

        folder_rel = folder or _MEMORY_LEVEL_FOLDER.get(str(fm.get("memory_level") or "").lower(), "00_Inbox")
        target_dir = self.vault_path / folder_rel
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{_sanitize_note_id(note_id)}.md"
        sections_out = sections if sections is not None else (_body_to_sections(body) if body else None)
        path.write_text(render_note_markdown(fm, sections_out), encoding="utf-8")
        self._maybe_git_commit(f"memory-vault: create {note_id}")
        return {"ok": True, "note_id": note_id, "path": str(path.relative_to(self.vault_path)),
                "validation": validation}

    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
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
        validation = validate_note_frontmatter(fm)
        fm["schema_status"] = validation["schema_status"]
        p.write_text(render_note_markdown(fm, sections), encoding="utf-8")
        self._maybe_git_commit(f"memory-vault: update {note_id}")
        return {"ok": True, "note_id": note_id, "path": str(p.relative_to(self.vault_path)), "validation": validation}

    def delete(self, note_id: str) -> Dict[str, Any]:
        p = self._find_note_path(note_id)
        if p is None:
            return {"ok": False, "error": "NOT_FOUND"}
        p.unlink()
        self._maybe_git_commit(f"memory-vault: delete {note_id}")
        return {"ok": True, "note_id": note_id}

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

    def _candidate_paths(self, term: str) -> List[Path]:
        if not term:
            return self._iter_notes()
        rg = shutil.which("rg")
        if not rg:
            return self._iter_notes()
        try:
            proc = subprocess.run(
                [rg, "-l", "-i", "-F", "--glob", "*.md", term, str(self.vault_path)],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode not in (0, 1):  # 1 == "ran fine, zero matches"
                return self._iter_notes()
            return [Path(line) for line in proc.stdout.splitlines() if line.strip()]
        except Exception:  # pragma: no cover - rg must never be a hard dependency for correctness
            return self._iter_notes()

    def _maybe_git_commit(self, message: str) -> None:
        if self.git_enabled:
            _commit_vault_change(self.vault_path, message)


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
               body: Optional[str] = None) -> Dict[str, Any]:
        return self._dispatch("create", frontmatter, sections, body)

    def update(self, note_id: str, frontmatter_patch: Optional[Dict[str, Any]] = None,
               sections_patch: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self._dispatch("update", note_id, frontmatter_patch, sections_patch)

    def delete(self, note_id: str) -> Dict[str, Any]:
        return self._dispatch("delete", note_id)

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

def build_frontmatter_from_memory_record(destination: str, mem: Dict[str, Any],
                                          project_name: Optional[str] = None) -> Dict[str, Any]:
    """Maps a MemoryStore/OrganizationalMemoryStore record onto the Phase 7
    note schema. Fields the record simply doesn't carry (rtl_sha, tb_sha,
    vip_vendor, ...) are emitted as null rather than omitted, so the note's
    own frontmatter always shows the full schema shape."""
    level = "engineering" if destination == "ENGINEERING_MEMORY" else "organizational"
    created = mem.get("created_at")
    created_iso = _epoch_to_iso(created) if isinstance(created, (int, float)) else (created or _now_iso())
    tags = sorted({str(v).lower().replace(" ", "-") for v in
                   (mem.get("protocol"), mem.get("scope"), level, mem.get("confidence")) if v})
    last_confirmed = mem.get("last_confirmed_at")
    return {
        "id": mem.get("memory_id") or mem.get("ccl_id") or _gen_note_id(),
        "memory_level": level,
        "protocol": mem.get("protocol"),
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
