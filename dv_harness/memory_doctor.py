"""Health check for the DV-Knowledge Vault (Phase 21 of the Obsidian+Git/
Markdown Hybrid Engineering Memory spec, Workstream 2).

Real checks, run against the actual vault on disk -- no simulated/hardcoded
verdicts:
  - vault exists/writable
  - git status (only meaningful when memory.git_enabled is True -- see
    check_git()'s own docstring for why "disabled" is not itself a defect)
  - Obsidian CLI detected (memory_vault.detect_obsidian_cli(), unchanged --
    this module never re-derives that probe)
  - filesystem fallback active (memory_vault.FileSystemMarkdownAdapter's own
    detect())
  - schema validity across every real Memory Note (validate_note_frontmatter()
    run over the actual 06_Agent_Memory/** notes, never a synthetic sample)
  - broken wiki-links, duplicate note IDs, invalid/unparsable YAML
    frontmatter, missing required metadata
  - large/forbidden-artifact files (an own, documented heuristic -- see
    LARGE_FILE_EXTENSIONS below; Phase 12's forbidden-artifact list is a
    separate, differently-scoped workstream's deliverable and was not yet
    available as importable code when this was written, so this defines its
    own conservative extension/size heuristic rather than blocking on that
    dependency)
  - secret leakage (dv_harness/memory_security.py's real detector, run over
    every note's raw on-disk text -- should normally find nothing, since
    memory_vault.py's create()/update() already redact before writing, but
    this re-checks the actual files, catching a hand-edited note or a note
    written before this feature existed)
  - JSON MemoryStore index integrity (2026-09-03): the 5-tier JSON store
    (dv_harness/memory.py) that the vault notes MIRROR, not the vault itself
    -- deliberately included here because it is the system of record behind
    every Memory Note, and a record file with no index.json row is invisible
    to MemoryRetriever.search() while still looking perfectly healthy in the
    vault. Read-only here; `python -m dv_harness.memory_cli reindex` repairs.

Only `06_Agent_Memory/**/*.md` is scanned for schema/duplicate-ID/invalid-
YAML/broken-link/secret checks -- Phase 7's Memory Note schema applies to
that tier's actual Memory Notes, not to the rest of the DV-Knowledge Vault
(00_Inbox, 02_Protocols, 05_Tools, etc.), which is general Obsidian-vault
space a human or other tooling may populate with ordinary, non-schema'd
Markdown. The large-file/forbidden-artifact check is scoped to the WHOLE
vault tree instead, since an accidentally-dropped FSDB/VPD/coverage-DB file
could land anywhere.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import memory_vault as mv
from . import memory_security as msec

# Own, documented large/forbidden-artifact heuristic (see module docstring
# for why this doesn't defer to Phase 12's list). Extensions in this set are
# flagged at ANY nonzero size -- these should never legitimately exist inside
# a Markdown knowledge vault at all. Everything else is judged purely by size.
LARGE_FILE_EXTENSIONS = {".fsdb", ".vpd", ".vdb", ".shm", ".db", ".wdb", ".fsdb.gz", ".vcd"}
LARGE_FILE_SIZE_BYTES = 5 * 1024 * 1024   # 5 MB -- any other non-.md file past this size
HUGE_LOG_SIZE_BYTES = 20 * 1024 * 1024    # 20 MB -- a plain .log/.txt only flagged past this size


def _memory_notes_root(vault_path: Path) -> Path:
    return vault_path / "06_Agent_Memory"


def _scan_notes(vault_path: Path) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    root = _memory_notes_root(vault_path)
    if not root.exists():
        return notes
    for p in sorted(root.rglob("*.md")):
        if ".git" in p.parts:
            continue
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError as exc:
            notes.append({"path": p, "raw": None, "frontmatter": None, "body": None,
                          "parsed_ok": False, "read_error": str(exc)})
            continue
        frontmatter, body = mv.parse_note_markdown(raw)
        parsed_ok = bool(frontmatter) and raw.lstrip().startswith("---")
        notes.append({"path": p, "raw": raw, "frontmatter": frontmatter, "body": body, "parsed_ok": parsed_ok})
    return notes


def check_vault_writable(vault_path: Path) -> Dict[str, Any]:
    try:
        vault_path.mkdir(parents=True, exist_ok=True)
        probe = vault_path / ".dv_harness_doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {"status": "READY", "writable": True}
    except OSError as exc:
        return {"status": "BLOCKED", "writable": False, "error": str(exc)}


def check_git(vault_path: Path, git_enabled: bool) -> Dict[str, Any]:
    """`git_enabled=False` is this project's own deliberate, documented
    default (config.py's DEFAULT_CONFIG comment, and the real regression it
    prevents) -- NOT a defect, so it reports "DISABLED" rather than
    PARTIAL/BLOCKED and does not drag the overall doctor verdict down.
    Only an ENABLED-but-broken git integration (no `git` on PATH, no repo
    initialized yet, or real uncommitted changes) is ever flagged."""
    if not git_enabled:
        return {"status": "DISABLED", "enabled": False,
                "reason": "memory.git_enabled is False (opt-in feature, not configured for this "
                          "project) -- informational, not a defect."}
    if shutil.which("git") is None:
        return {"status": "PARTIAL", "enabled": True,
                "reason": "memory.git_enabled is True but no `git` executable was found on PATH."}
    if not (vault_path / ".git").exists():
        return {"status": "PARTIAL", "enabled": True,
                "reason": "memory.git_enabled is True but the vault has no .git repo yet "
                          "(no note has been written through it yet)."}
    result = mv._run_git(vault_path, ["status", "--porcelain"])
    if result is None or result.returncode != 0:
        return {"status": "PARTIAL", "enabled": True, "reason": "`git status` failed against the vault repo."}
    pending = [l for l in result.stdout.splitlines() if l.strip()]
    return {
        "status": "READY" if not pending else "PARTIAL", "enabled": True,
        "uncommitted_changes": len(pending),
        "reason": None if not pending else f"{len(pending)} uncommitted change(s) in the vault git repo.",
    }


def check_obsidian() -> Dict[str, Any]:
    report = mv.detect_obsidian_cli()
    if not report["installed"]:
        reason = ("Obsidian CLI is not installed on this machine -- an expected, permanent state on "
                   "every machine confirmed so far, not a bug; the real, always-available write path "
                   "is the filesystem adapter (see HybridMemoryProvider).")
    else:
        reason = ("Obsidian CLI detected but its operations are not wired against a confirmed command "
                   "contract yet (see ObsidianAdapter's own docstring) -- the filesystem adapter remains "
                   "the active write path.")
    return {"status": report["status"], "installed": report["installed"], "version": report["version"],
            "reason": reason}


def check_filesystem_fallback(vault_path: Path) -> Dict[str, Any]:
    fs = mv.FileSystemMarkdownAdapter(vault_path, git_enabled=False)
    d = fs.detect()
    return {"status": d["status"], "vault_access": d["vault_access"]}


def check_schema(notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    complete: List[Dict[str, Any]] = []
    partial: List[Dict[str, Any]] = []
    for n in notes:
        if not n.get("parsed_ok"):
            continue  # counted by check_invalid_yaml() instead
        v = mv.validate_note_frontmatter(n["frontmatter"])
        entry = {"note_id": n["frontmatter"].get("id") or n["path"].stem, "path": str(n["path"])}
        if v["schema_status"] == "COMPLETE":
            complete.append(entry)
        else:
            entry["missing_required"] = v["missing_required"]
            partial.append(entry)
    return {"status": "PARTIAL" if partial else "READY", "complete_count": len(complete), "partial": partial}


def check_duplicate_ids(notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    seen: Dict[str, List[str]] = {}
    for n in notes:
        if not n.get("parsed_ok"):
            continue
        nid = n["frontmatter"].get("id")
        if not nid:
            continue
        seen.setdefault(nid, []).append(str(n["path"]))
    dupes = {nid: paths for nid, paths in seen.items() if len(paths) > 1}
    return {"status": "BLOCKED" if dupes else "READY", "duplicates": dupes}


def check_invalid_yaml(notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    invalid = [str(n["path"]) for n in notes if not n.get("parsed_ok")]
    return {"status": "BLOCKED" if invalid else "READY", "invalid_notes": invalid}


def check_broken_links(notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    known_ids = {n["frontmatter"].get("id") or n["path"].stem for n in notes if n.get("parsed_ok")}
    broken = []
    for n in notes:
        if not n.get("parsed_ok"):
            continue
        targets = set(mv._WIKILINK_RE.findall(n["body"] or ""))
        missing = sorted(t for t in targets if t not in known_ids)
        if missing:
            broken.append({"note_id": n["frontmatter"].get("id") or n["path"].stem,
                            "path": str(n["path"]), "broken_links": missing})
    return {"status": "PARTIAL" if broken else "READY", "notes_with_broken_links": broken}


def check_large_files(vault_path: Path) -> Dict[str, Any]:
    flagged = []
    if vault_path.exists():
        for p in vault_path.rglob("*"):
            if not p.is_file() or ".git" in p.parts:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            ext = p.suffix.lower()
            if ext in LARGE_FILE_EXTENSIONS and size > 0:
                flagged.append({"path": str(p.relative_to(vault_path)), "size_bytes": size,
                                 "reason": f"forbidden-artifact extension {ext} inside a Markdown vault"})
            elif ext in (".log", ".txt") and size > HUGE_LOG_SIZE_BYTES:
                flagged.append({"path": str(p.relative_to(vault_path)), "size_bytes": size,
                                 "reason": "huge log/text file (accidentally-committed raw log?)"})
            elif ext not in (".md", ".log", ".txt") and size > LARGE_FILE_SIZE_BYTES:
                flagged.append({"path": str(p.relative_to(vault_path)), "size_bytes": size,
                                 "reason": "non-note file exceeds the large-artifact size threshold"})
    return {"status": "PARTIAL" if flagged else "READY", "flagged": flagged}


def check_secrets(notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    found = []
    for n in notes:
        if n.get("raw") is None:
            continue
        findings = msec.detect_secrets(n["raw"])
        if findings:
            found.append({"path": str(n["path"]), "findings": findings})
    return {"status": "BLOCKED" if found else "READY", "notes_with_secrets": found}


def check_memory_store_index(root: Path) -> Dict[str, Any]:
    """JSON MemoryStore index-vs-files drift (see module docstring). A record
    file with no index.json row is PARTIAL, not BLOCKED: the record itself is
    intact and still reachable by exact memory_id via MemoryStore.get(), it
    is only invisible to search -- and `python -m dv_harness.memory_cli
    reindex` closes it without any data loss."""
    from .memory import MemoryStore
    try:
        report = MemoryStore(Path(root)).index_integrity()
    except (OSError, ValueError) as exc:
        return {"status": "PARTIAL", "error": str(exc)}
    if report["ok"]:
        return {"status": "READY", **report}
    missing = len(report["files_missing_from_index"])
    orphaned = len(report["index_rows_without_file"])
    return {
        "status": "PARTIAL",
        "reason": (f"{missing} record file(s) have no index.json row (invisible to "
                    f"MemoryRetriever.search()); {orphaned} index row(s) point at a missing file. "
                    f"Repair with `python -m dv_harness.memory_cli reindex`."),
        **report,
    }


def _aggregate(checks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    blocked = [k for k, v in checks.items() if v.get("status") == "BLOCKED"]
    partial = [k for k, v in checks.items() if v.get("status") == "PARTIAL"]
    overall = "BLOCKED" if blocked else ("PARTIAL" if partial else "READY")
    return {"overall": overall, "blocked_reasons": blocked, "partial_reasons": partial}


def run_validate(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The note-CORRECTNESS subset of run_doctor() below (schema, duplicate
    IDs, invalid YAML, broken links, secret leakage) -- everything that is
    actually about the vault's own content, none of the environment checks
    (vault-writable/git/Obsidian/filesystem-adapter/large-files) `doctor`
    additionally runs. Backs the `dv-harness memory validate` CLI
    subcommand."""
    if cfg is None:
        from .config import load_config
        cfg = load_config(root)
    vault_path = mv.resolve_vault_path(root, cfg)
    notes = _scan_notes(vault_path)
    checks = {
        "schema": check_schema(notes),
        "duplicate_ids": check_duplicate_ids(notes),
        "invalid_yaml": check_invalid_yaml(notes),
        "broken_links": check_broken_links(notes),
        "secrets": check_secrets(notes),
    }
    result = _aggregate(checks)
    result.update({"note_count": len(notes), "checks": checks})
    return result


def run_doctor(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Phase 21: the full health check across everything the spec names.
    See this module's own docstring for exactly what each check covers and
    module docstring's opening summary for the BLOCKED/PARTIAL/READY
    aggregation rule (BLOCKED trumps PARTIAL trumps READY; `git`'s
    deliberate DISABLED state and `READY` never contribute to either)."""
    if cfg is None:
        from .config import load_config
        cfg = load_config(root)
    memory_cfg = cfg.get("memory") or {}
    vault_path = mv.resolve_vault_path(root, cfg)
    notes = _scan_notes(vault_path)

    checks = {
        "vault_writable": check_vault_writable(vault_path),
        "git": check_git(vault_path, bool(memory_cfg.get("git_enabled", False))),
        "obsidian_cli": check_obsidian(),
        "filesystem_fallback": check_filesystem_fallback(vault_path),
        "schema": check_schema(notes),
        "duplicate_ids": check_duplicate_ids(notes),
        "invalid_yaml": check_invalid_yaml(notes),
        "broken_links": check_broken_links(notes),
        "large_files": check_large_files(vault_path),
        "secrets": check_secrets(notes),
        "memory_store_index": check_memory_store_index(root),
    }

    result = _aggregate(checks)
    result.update({"vault_path": str(vault_path), "note_count": len(notes), "checks": checks})
    return result
