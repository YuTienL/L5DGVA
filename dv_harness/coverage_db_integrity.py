"""dv_harness/coverage_db_integrity.py -- the coverage database MERGE
INTEGRITY gate (2026-09-06).

THE GAP THIS CLOSES
--------------------
Coverage merge (rolling several regression runs' coverage databases into one
signoff-counted total) had no integrity check anywhere in this repo. A
repo-wide grep before writing this confirmed it: nothing named
`coverage_merge`/`merge_integrity`/`coverage_db` existed, and
`coverage_analysis.py`'s own module docstring already discloses the
boundary this module respects -- "this operates on a coverage summary that
has ALREADY been reduced to plain JSON by whatever real coverage tool the
project uses... If no such file exists yet, there is nothing to run this
against." That module trusts its input JSON as given. Nothing asked, before
a merge counts toward signoff, whether the files being merged are what they
claim to be, or whether they were produced by compatible tooling.

TWO CHECKS, EACH GROUNDED IN A REAL PRODUCER -- NOTHING INVENTED
-----------------------------------------------------------------
(a) CONTENT FINGERPRINT. `connectivity_check.py`'s `compute_rtl_fingerprint()`
    already does this for RTL sources, but it is RTL-specific by
    construction (it walks a project's declared `rtl_sources` globs) and its
    own per-file hasher, `_hash_file()`, is a private module helper -- not
    published for reuse. `env_manifest.py`'s `file_ref()` (public since
    2026-09-06, "so a supply-chain report and an env.manifest.json describe
    the same file identically -- a second hashing helper would be two
    answers to which file did this artifact read") is the SAME sha256-of-
    file primitive, already exported for exactly this kind of reuse and
    already reused by `dependency_supply_chain.py`. This module imports it
    rather than writing a third hasher, and combines per-file digests using
    the identical scheme `compute_rtl_fingerprint()` established (sorted
    relative paths, `path \\0 digest \\n` folded into one sha256) so the
    combination rule has one definition in this codebase, not two.
    `verify_fingerprint_claim()` recomputes this fingerprint from the real
    bytes on disk and compares it against whatever fingerprint the merge
    request CLAIMS for that coverage DB (e.g. recorded when the DB was
    staged for merge) -- the same "recompute and compare against a prior
    claim" shape `connectivity_check.py`'s own staleness trigger uses for
    RTL, applied here to detect a coverage DB substituted or altered between
    being staged and being merged.

(b) TOOL/CONFIG COMPATIBILITY. Checked BEFORE building this: does any real
    producer in this codebase record a coverage DATABASE's own tool/version
    identity? `coverage_analysis.parse_coverage_summary()`'s schema is
    `{"categories": [{"name","percent","bins_total","bins_hit"}]}` -- no
    tool/version field exists there, and that function actively DISCARDS any
    extra key a raw summary JSON might carry (it rebuilds each validated
    category from exactly those four fields), so reading an ad hoc
    "tool_version" key out of a coverage summary would be inventing a field
    this project's own real parser throws away. `env_manifest.py` DOES
    record two real, already-written tool/version facts for the environment
    that produced a run's coverage: `generator.tool_version` (schema 1.2,
    section 210's per-artifact generation provenance -- the real
    `dv_harness.__version__` that generated env.manifest.json) and
    `vip_config.vip_release` (the real `$DESIGNWARE_HOME` filesystem scan --
    which VIP package/version this environment is actually built against,
    not a version typed into a document). Neither is per-coverage-DB by
    itself; what this module does is let a merge request ASSOCIATE each
    coverage DB entry with the env.manifest.json its own run produced (a
    real, already-schema-validated artifact this project's env-manifest
    pipeline already writes) and compare those two real fields ACROSS the
    entries being merged. An entry with no associated env.manifest.json
    contributes NOT_AVAILABLE identity, named as such -- never a fabricated
    "compatible" verdict, per the Evidence Truth Rule.

THREE VERDICTS, NEVER TWO COLLAPSED INTO ONE
---------------------------------------------
MERGE_ALLOWED (every fingerprint claim matched, every recorded tool/config
identity agreed), MERGE_BLOCKED (a real finding -- a fingerprint mismatch, a
real tool/VIP-version disagreement), MERGE_NOT_VERIFIABLE (no finding, but
something could not be checked -- a fingerprint with no claim to compare
against, an entry with no associated env.manifest.json). Collapsing the
latter two into one "BLOCKED" would erase a distinction the Evidence Truth
Rule requires ("never collapse two different kinds of unknown into one
value") -- a proven disagreement and an absence of evidence are different
operator problems with different fixes, the same distinction
`signoff_export.py`'s INVALIDATED-vs-INDETERMINATE and `waiver_store.py`'s
EXPIRED-vs-UNKNOWN already keep. What both verdicts share, and the reason
neither is silently a pass: only MERGE_ALLOWED exits 0. A merge that could
not be verified is not silently counted toward signoff any more than one
that was proven incompatible is -- "never silently merge incompatible or
unverifiable coverage data into a signoff-counted total."

DELIBERATELY BOUNDED
---------------------
This module never opens a real coverage database (UCIS/urg/vdb) and never
parses coverage bins -- that boundary belongs to whatever real coverage tool
already reduced it to the JSON `coverage_analysis.py` consumes, and reading
one here would be exactly the "no such parser, do not invent one" limit that
module's own docstring already states. This module only fingerprints FILE
CONTENT (whatever files sit under a declared coverage-DB path) and compares
already-real recorded facts. It ARBITRATES nothing: no merge is performed
here, no coverage total is computed, and there is deliberately no stage
gate -- a gate that passed on a merge nobody actually verified would be
worse than none.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import env_manifest

#: The three merge verdicts. Never collapsed -- see module docstring.
MERGE_ALLOWED = "MERGE_ALLOWED"
MERGE_BLOCKED = "MERGE_BLOCKED"
MERGE_NOT_VERIFIABLE = "MERGE_NOT_VERIFIABLE"
MERGE_VERDICTS = (MERGE_ALLOWED, MERGE_BLOCKED, MERGE_NOT_VERIFIABLE)

#: Per-entry fingerprint check outcomes.
FINGERPRINT_MATCH = "MATCH"
FINGERPRINT_MISMATCH = "MISMATCH"
FINGERPRINT_NOT_AVAILABLE = "NOT_AVAILABLE"

#: Cross-entry tool/config compatibility outcomes.
TOOL_CONFIG_COMPATIBLE = "COMPATIBLE"
TOOL_CONFIG_INCOMPATIBLE = "INCOMPATIBLE"
TOOL_CONFIG_NOT_AVAILABLE = "NOT_AVAILABLE"


class CoverageDbIntegrityError(ValueError):
    """Raised for a malformed merge-request document -- never for a real
    finding about the coverage data itself (that is a report field, not an
    exception), mirroring `CoverageAnalysisError`'s own reason/detail shape."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# (a) content fingerprint
# ---------------------------------------------------------------------------

def collect_coverage_db_files(db_path) -> List[Path]:
    """Every real file under `db_path`, sorted. `db_path` may be a single
    file (e.g. a reduced coverage summary JSON) or a directory (e.g. a
    merged coverage database's own output tree) -- a coverage DB is not
    always one file, and this module fingerprints whatever real files are
    actually there rather than assuming a shape."""
    p = Path(db_path)
    if p.is_file():
        return [p]
    if p.is_dir():
        return sorted(f for f in p.rglob("*") if f.is_file())
    return []


def compute_coverage_db_fingerprint(db_path) -> dict:
    """Content fingerprint of the real files under `db_path`, using
    `env_manifest.file_ref()` per file (the same public sha256-of-file
    helper `dependency_supply_chain.py` already reuses) and
    `connectivity_check.compute_rtl_fingerprint()`'s own combination scheme
    (sorted relative path + digest folded into one sha256) so this
    codebase has one definition of "combine per-file digests into one
    fingerprint", not two. Hashes CONTENT, never mtime, for the same reason
    the RTL fingerprint does: a no-op touch must not look like a change,
    and a content change that preserves mtime must not be missed."""
    p = Path(db_path)
    if not p.exists():
        return {"status": FINGERPRINT_NOT_AVAILABLE,
                 "reason": f"coverage DB path does not exist: {p}",
                 "fingerprint": None, "file_count": 0, "files": {}}
    files = collect_coverage_db_files(p)
    if not files:
        return {"status": FINGERPRINT_NOT_AVAILABLE,
                 "reason": f"coverage DB path contains no real files to fingerprint: {p}",
                 "fingerprint": None, "file_count": 0, "files": {}}
    base = p if p.is_dir() else p.parent
    h = hashlib.sha256()
    per_file: Dict[str, str] = {}
    for f in files:
        rel = f.relative_to(base).as_posix()
        digest = env_manifest.file_ref(f)["sha256"]
        per_file[rel] = digest
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    return {"status": "COMPUTED", "reason": None,
             "fingerprint": h.hexdigest(), "file_count": len(files), "files": per_file}


def verify_fingerprint_claim(db_path, claimed_fingerprint: Optional[str]) -> dict:
    """Recomputes the real fingerprint and compares it against
    `claimed_fingerprint` (whatever the merge request says this coverage DB
    is supposed to hash to -- e.g. recorded when it was staged for merge).
    NOT_AVAILABLE (never MATCH/MISMATCH) when the path cannot be
    fingerprinted at all, or when no claim was supplied to check against --
    "we could not check" is not evidence of either outcome."""
    computed = compute_coverage_db_fingerprint(db_path)
    if computed["status"] != "COMPUTED":
        return {"status": FINGERPRINT_NOT_AVAILABLE, "reason": computed["reason"],
                 "computed_fingerprint": None, "claimed_fingerprint": claimed_fingerprint,
                 "file_count": 0}
    if not claimed_fingerprint:
        return {"status": FINGERPRINT_NOT_AVAILABLE,
                 "reason": f"no fingerprint was claimed for coverage DB at {db_path} -- "
                            "nothing to verify its content against",
                 "computed_fingerprint": computed["fingerprint"], "claimed_fingerprint": None,
                 "file_count": computed["file_count"]}
    if claimed_fingerprint == computed["fingerprint"]:
        return {"status": FINGERPRINT_MATCH, "reason": None,
                 "computed_fingerprint": computed["fingerprint"],
                 "claimed_fingerprint": claimed_fingerprint, "file_count": computed["file_count"]}
    return {"status": FINGERPRINT_MISMATCH,
             "reason": f"coverage DB at {db_path} claimed fingerprint {claimed_fingerprint!r} but "
                        f"its real on-disk content hashes to {computed['fingerprint']!r} -- content "
                        "changed or was substituted since the claim was recorded",
             "computed_fingerprint": computed["fingerprint"], "claimed_fingerprint": claimed_fingerprint,
             "file_count": computed["file_count"]}


# ---------------------------------------------------------------------------
# (b) tool/config identity + cross-entry compatibility
# ---------------------------------------------------------------------------

def extract_tool_identity(env_manifest_path) -> dict:
    """Reads the REAL tool/VIP identity an env.manifest.json already
    records for the run that produced one coverage DB -- `generator.
    tool_version` (env_manifest.py schema 1.2's own per-artifact provenance
    tuple) and `vip_config.vip_release` (the real $DESIGNWARE_HOME scan).
    NOT_AVAILABLE, with the real reason, when no manifest was associated, it
    does not exist, or it does not validate -- this module never invents a
    tool/version fact a coverage DB itself carries no field for."""
    if not env_manifest_path:
        return {"status": TOOL_CONFIG_NOT_AVAILABLE,
                 "reason": "no env.manifest.json was associated with this coverage DB entry -- "
                            "this project has no other producer of tool/config identity for a "
                            "coverage database itself (coverage_analysis.parse_coverage_summary's "
                            "schema records only name/percent/bins_total/bins_hit, no tool/version "
                            "field)",
                 "tool": None, "tool_version": None, "schema_version": None,
                 "vip_release_status": None, "vip_packages": None, "source_path": None}
    p = Path(env_manifest_path)
    if not p.is_file():
        return {"status": TOOL_CONFIG_NOT_AVAILABLE,
                 "reason": f"declared env.manifest.json does not exist: {p}",
                 "tool": None, "tool_version": None, "schema_version": None,
                 "vip_release_status": None, "vip_packages": None, "source_path": str(p)}
    try:
        manifest = env_manifest.load_env_manifest(p)
    except (env_manifest.EnvManifestValidationError, ValueError, OSError) as exc:
        return {"status": TOOL_CONFIG_NOT_AVAILABLE,
                 "reason": f"env.manifest.json at {p} could not be loaded/validated: {exc}",
                 "tool": None, "tool_version": None, "schema_version": None,
                 "vip_release_status": None, "vip_packages": None, "source_path": str(p)}
    prov = env_manifest.generation_provenance(manifest)
    vip_release = ((manifest.get("vip_config") or {}).get("vip_release")) or {}
    vip_status = vip_release.get("status")
    packages = vip_release.get("packages") if vip_status == "SCANNED" else None
    vip_packages = (
        [{"name": pkg.get("name"), "version": pkg.get("version")} for pkg in packages]
        if packages is not None else None
    )
    return {"status": "RECORDED", "reason": None,
             "tool": prov.get("tool"), "tool_version": prov.get("tool_version"),
             "schema_version": prov.get("schema_version"),
             "vip_release_status": vip_status, "vip_packages": vip_packages,
             "source_path": str(p)}


def analyze_tool_config_compatibility(identities: Sequence[dict]) -> dict:
    """Compares real tool/VIP identity across every entry being merged.
    COMPATIBLE only when every entry recorded identity AND they all agree.
    INCOMPATIBLE names every disagreeing field. NOT_AVAILABLE (never a
    fabricated COMPATIBLE) when nothing was recorded at all, or when some
    entries recorded identity and others did not -- a partial view cannot
    prove the whole merge is compatible."""
    recorded = [i for i in identities if i["status"] == "RECORDED"]
    total = len(identities)
    if not recorded:
        return {"status": TOOL_CONFIG_NOT_AVAILABLE,
                 "reason": "no coverage DB entry being merged carries a recorded tool/config "
                            "identity -- pass env_manifest_path for at least one entry to compare "
                            "generator.tool_version / vip_config.vip_release across the merge",
                 "mismatches": [], "recorded_count": 0, "total_count": total}

    mismatches = []
    tool_versions = sorted({i["tool_version"] for i in recorded if i["tool_version"]})
    if len(tool_versions) > 1:
        mismatches.append({"field": "generator.tool_version", "values": tool_versions})

    pkg_versions: Dict[str, set] = {}
    for i in recorded:
        for pkg in (i["vip_packages"] or []):
            pkg_versions.setdefault(pkg["name"], set()).add(pkg["version"])
    for name in sorted(pkg_versions):
        versions = sorted(v for v in pkg_versions[name] if v is not None)
        if len(pkg_versions[name]) > 1:
            mismatches.append({"field": f"vip_config.vip_release.packages[{name}]", "values": versions})

    if mismatches:
        detail = "; ".join(f"{m['field']}={m['values']}" for m in mismatches)
        return {"status": TOOL_CONFIG_INCOMPATIBLE,
                 "reason": f"coverage DB entries being merged were produced by disagreeing "
                            f"tool/VIP versions: {detail}",
                 "mismatches": mismatches, "recorded_count": len(recorded), "total_count": total}

    if len(recorded) < total:
        missing = total - len(recorded)
        return {"status": TOOL_CONFIG_NOT_AVAILABLE,
                 "reason": f"{missing} of {total} coverage DB entries recorded no tool/config "
                            "identity -- compatibility could not be fully verified across all "
                            "entries being merged",
                 "mismatches": [], "recorded_count": len(recorded), "total_count": total}

    return {"status": TOOL_CONFIG_COMPATIBLE, "reason": None,
             "mismatches": [], "recorded_count": len(recorded), "total_count": total}


# ---------------------------------------------------------------------------
# merge-level analysis
# ---------------------------------------------------------------------------

def _validate_entry(entry: Any) -> dict:
    if not isinstance(entry, dict) or not entry.get("db_path"):
        raise CoverageDbIntegrityError(
            "ENTRY_MISSING_DB_PATH",
            {"reason": "each merge entry must be an object carrying a non-empty 'db_path'",
             "entry": entry},
        )
    return entry


def analyze_coverage_db_merge(entries: Sequence[dict]) -> dict:
    """The merge integrity report: per-entry fingerprint verification plus
    the cross-entry tool/config compatibility check, folded into one of the
    three MERGE_VERDICTS. No entries at all is honestly
    MERGE_NOT_VERIFIABLE (there is nothing to verify), never a vacuous
    MERGE_ALLOWED."""
    entries = [_validate_entry(e) for e in entries]
    if not entries:
        return {"verdict": MERGE_NOT_VERIFIABLE,
                 "reason": "no coverage DB entries were supplied to merge -- nothing to verify",
                 "entry_count": 0, "entries": [],
                 "tool_config_compatibility": {
                     "status": TOOL_CONFIG_NOT_AVAILABLE,
                     "reason": "no entries supplied", "mismatches": [],
                     "recorded_count": 0, "total_count": 0}}

    per_entry = []
    identities = []
    for e in entries:
        label = e.get("label") or e["db_path"]
        fp = verify_fingerprint_claim(e["db_path"], e.get("claimed_fingerprint"))
        ident = extract_tool_identity(e.get("env_manifest_path"))
        identities.append(ident)
        per_entry.append({"label": label, "db_path": e["db_path"],
                            "fingerprint_check": fp, "tool_identity": ident})

    tool_compat = analyze_tool_config_compatibility(identities)

    reasons = []
    mismatched = [pe for pe in per_entry if pe["fingerprint_check"]["status"] == FINGERPRINT_MISMATCH]
    for pe in mismatched:
        reasons.append(f"{pe['label']}: {pe['fingerprint_check']['reason']}")
    if tool_compat["status"] == TOOL_CONFIG_INCOMPATIBLE:
        reasons.append(tool_compat["reason"])

    if mismatched or tool_compat["status"] == TOOL_CONFIG_INCOMPATIBLE:
        verdict = MERGE_BLOCKED
    else:
        unverifiable = [pe["label"] for pe in per_entry
                          if pe["fingerprint_check"]["status"] == FINGERPRINT_NOT_AVAILABLE]
        if unverifiable:
            reasons.append("fingerprint could not be verified for: " + ", ".join(unverifiable))
        if tool_compat["status"] == TOOL_CONFIG_NOT_AVAILABLE:
            reasons.append(tool_compat["reason"])
        verdict = MERGE_NOT_VERIFIABLE if (unverifiable or tool_compat["status"] == TOOL_CONFIG_NOT_AVAILABLE) else MERGE_ALLOWED

    reason = "; ".join(reasons) if reasons else (
        "all coverage DB entries verified: content fingerprints match their claims and "
        "recorded tool/VIP-config identity agrees across the merge")

    return {"verdict": verdict, "reason": reason, "entry_count": len(entries),
             "entries": per_entry, "tool_config_compatibility": tool_compat}


def load_merge_request(path) -> List[dict]:
    """Reads a merge-request JSON file: `{"entries": [{"label"?, "db_path",
    "claimed_fingerprint"?, "env_manifest_path"?}, ...]}`."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageDbIntegrityError(
            "MERGE_REQUEST_UNREADABLE", {"path": str(p), "error": str(exc)}
        ) from exc
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise CoverageDbIntegrityError(
            "MERGE_REQUEST_MALFORMED",
            {"reason": "merge request must be an object carrying a list 'entries'", "path": str(p)},
        )
    return entries


# ---------------------------------------------------------------------------
# front door
# ---------------------------------------------------------------------------

EXIT_ALLOWED = 0
EXIT_BLOCKED = 1
EXIT_NOT_VERIFIABLE = 2

_EXIT_FOR_VERDICT = {MERGE_ALLOWED: EXIT_ALLOWED, MERGE_BLOCKED: EXIT_BLOCKED,
                      MERGE_NOT_VERIFIABLE: EXIT_NOT_VERIFIABLE}


def execute_verb(argv: Sequence[str]) -> int:
    """Shared implementation for `python -m dv_harness.coverage_db_integrity`
    (no `dv-harness` CLI wiring -- `cli.py` is a ~4100-line argparse tree
    under concurrent modification by other work in this session, the same
    reason `waiver_store.py`/`signoff_export.py` also expose only this ad
    hoc front door)."""
    ap = argparse.ArgumentParser(prog="coverage-db-integrity", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)

    p_fp = sub.add_parser("fingerprint", help="Compute the real content fingerprint of one "
                                                "coverage DB path (file or directory).")
    p_fp.add_argument("--db-path", required=True)

    p_chk = sub.add_parser("check", help="Verify a merge request: per-entry fingerprint claims "
                                           "plus cross-entry tool/config compatibility.")
    p_chk.add_argument("--merge-request", required=True,
                        help="Path to a JSON file: {\"entries\": [{\"db_path\", "
                             "\"claimed_fingerprint\"?, \"env_manifest_path\"?, \"label\"?}, ...]}")

    args = ap.parse_args(list(argv))

    if args.verb == "fingerprint":
        report = compute_coverage_db_fingerprint(args.db_path)
        print(json.dumps(report, indent=2))
        return EXIT_ALLOWED if report["status"] == "COMPUTED" else EXIT_NOT_VERIFIABLE

    try:
        entries = load_merge_request(args.merge_request)
        report = analyze_coverage_db_merge(entries)
    except CoverageDbIntegrityError as exc:
        print(json.dumps({"error": exc.reason, "detail": exc.detail}, indent=2))
        return EXIT_NOT_VERIFIABLE

    print(json.dumps(report, indent=2))
    return _EXIT_FOR_VERDICT[report["verdict"]]


if __name__ == "__main__":
    sys.exit(execute_verb(sys.argv[1:]))
