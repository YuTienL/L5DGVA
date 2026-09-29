"""dv_harness/system_signoff_package.py -- System Signoff Package (2026-09-06).

THE GAP THIS CLOSES
--------------------
`signoff_export.py`'s `collect_signoff_bundle()` is a SINGLE-PROJECT (subsystem-
scope, IP-level) signoff bundle: it copies real artifacts off ONE project root
into ONE directory, computes ONE `bundle_hash`, and stamps a `SIGNOFF_GATE_
VERIFIED` / `PRE_SIGNOFF_GATE_INPUT` kind from that ONE project's own real
SIGNOFF stage-gate status. Nothing in this repo assembled the SYSTEM-scope
sibling: several real, already-real per-subsystem `SubsystemVerificationContract`
records (`subsystem_contract.py`) plus the system-level rollups
(`system_verification_contract.py`'s cross-subsystem topology/resource/command
reconciliation, `system_closure_aggregator.py`'s twelve-dimension closure fold)
into ONE exportable package a human can hand to a system-level signoff review.

REUSE OVER REINVENT -- THIS MODULE WRITES NO SECOND BUNDLER
--------------------------------------------------------------
Every one of the three inputs is produced by its OWN already-real, already-
tested module, called directly (not a claimed/concurrently-edited file as of
this writing -- verified before building):
  * `subsystem_contract.assemble_subsystem_contract()` -- called once per named
    subsystem against `root`, exactly as a human would run
    `python -m dv_harness.subsystem_contract assemble --subsystem <name>`.
  * `system_verification_contract.assemble_system_verification_contract()` --
    called once, over the real subsystem-contract records this module just
    assembled (plus whatever topology/resource-registry/command-registry
    documents a caller supplies).
  * `system_closure_aggregator.aggregate_system_closure()` -- called once, over
    a caller-supplied list of `{dimension_name, status}` closure-dimension
    records (this module invents none of the twelve dimensions' values; per
    that module's own file-safety scope it never imports the real per-domain
    closure modules either, so a caller assembles the dimension list from
    whichever of those it has run).

The BUNDLE MECHANICS -- never a second, parallel bundler -- are the exact ones
`signoff_export.collect_signoff_bundle()` already established and this module
imports directly: `signoff_export.compute_bundle_hash(manifest)` (the real,
independently-recomputable manifest-hash function -- sorted
`"{artifact}:{present}:{bundled_path}"` lines, sha256), and
`signoff_export._artifact_content_digest()` (the same file-or-directory content
hasher `collect_signoff_bundle()` itself calls for its own `content_sha256`
field). Every manifest entry this module writes has the IDENTICAL four-key
shape `collect_signoff_bundle()`'s own `record()` closure produces
(`artifact`/`present`/`bundled_path`/`content_sha256`), so a reader (or a
future completeness gate) parses a system-scope manifest.json exactly the way
it already parses a project-scope one.

WHAT THIS MODULE ADDS ON TOP OF THAT REUSED MECHANICS
--------------------------------------------------------
  * `package_kind` -- `SYSTEM_SIGNOFF_GATE_VERIFIED` only when EVERY assembled
    subsystem contract's own real `signoff.stage.gate_verified` is true (the
    real `signoff_export.read_signoff_stage_status()` value each subsystem
    contract already carries) AND the closure rollup's own real
    `overall_status` is `CLOSED` -- worst-wins across BOTH facts, mirroring
    this project's own composite-gate discipline (CLAUDE.md's "Worst-wins
    composite gates" rule): a single subsystem whose own SIGNOFF gate never
    passed, or a single closure dimension left open, makes the WHOLE package
    `PRE_SYSTEM_SIGNOFF_GATE_INPUT` regardless of how clean everything else
    is. `require_system_signoff_pass=True` (mirroring `signoff_export.
    collect_signoff_bundle()`'s own `require_signoff_pass`) turns that into a
    hard refusal that writes nothing at all, not even an empty `out_dir` --
    the identical "refusal writes nothing" contract that function already
    keeps, so an accidental partial/misleading package can never be produced
    by a caller who asked for a strict one. Default `False`, for the identical
    reason `collect_signoff_bundle()`'s own default is `False`: a package has
    to be PRODUCIBLE before a system-level SIGNOFF review can even look at it.
  * A `subsystem_index` naming every subsystem this package attempted to
    assemble, whether it was LIVE_ASSEMBLED (this module called
    `subsystem_contract.assemble_subsystem_contract()` itself against `root`)
    or CALLER_SUPPLIED (a caller already held a subsystem-contract-shaped
    record and handed it in directly -- the same duck-typed acceptance
    `system_verification_contract.py` itself already extends to its own
    `subsystem_contracts` parameter). A subsystem whose LIVE assembly raised
    is recorded honestly -- `present: False` in the manifest, the real
    exception text in `subsystem_index`, and it is EXCLUDED from what
    `system_verification_contract.py`/`system_closure_aggregator.py` see,
    exactly as `collect_signoff_bundle()` never fabricates a missing artifact.

EVIDENCE TRUTH RULE
--------------------
Nothing here invents a subsystem's completeness, a gate-verified status, or a
closure verdict. Every one of those is read verbatim off the real record its
owning module returned. A subsystem with nothing on disk to assemble from
still produces a real (honestly `NOT_AVAILABLE`/`PARTIAL`) contract record --
`subsystem_contract.assemble_subsystem_contract()`'s own contract, not this
module's -- and that honest incompleteness is what keeps `package_kind` at
`PRE_SYSTEM_SIGNOFF_GATE_INPUT` rather than being silently rounded up.

WHAT THIS MODULE IS NOT
------------------------
It DECIDES, ARBITRATES and WRITES NO GOVERNANCE STATE beyond the package
directory itself: no stage runs, no gate script is invoked, no build/
regression/LSF submission starts, no approval is minted, and no cross-subsystem
resource/ownership conflict is resolved (a `driver_conflicts`/
`blocking_decisions` finding inside the system-verification-contract section is
carried through as text for a human, exactly as `system_verification_contract.
py` itself already states). There is deliberately no `STAGE_GATES` entry -- a
gate that passed because a package existed, or failed because one did not,
would be worse than none. Per this project's own current file-safety guidance
(`cli.py`/`gates.py` are large, heavily-edited files this task must not touch),
there is no `dv-harness` CLI verb; the front door is
`python -m dv_harness.system_signoff_package collect ...`, the same disclosed
choice several recent sibling modules already make.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import signoff_export as se
from . import subsystem_contract as sc
from . import system_closure_aggregator as sca
from . import system_verification_contract as svc

SCHEMA_VERSION = "1.0"

#: Package-kind vocabulary. Mirrors `signoff_export.py`'s own
#: SIGNOFF_GATE_VERIFIED / PRE_SIGNOFF_GATE_INPUT naming, one level up (system
#: scope rather than one project's own SIGNOFF stage gate).
SYSTEM_SIGNOFF_GATE_VERIFIED = "SYSTEM_SIGNOFF_GATE_VERIFIED"
PRE_SYSTEM_SIGNOFF_GATE_INPUT = "PRE_SYSTEM_SIGNOFF_GATE_INPUT"
PACKAGE_KINDS: Tuple[str, ...] = (SYSTEM_SIGNOFF_GATE_VERIFIED, PRE_SYSTEM_SIGNOFF_GATE_INPUT)

#: Subsystem-record provenance -- was it live-assembled by THIS module against
#: `root`, or handed in already-built by the caller.
SOURCE_LIVE_ASSEMBLED = "LIVE_ASSEMBLED"
SOURCE_CALLER_SUPPLIED = "CALLER_SUPPLIED"


class SystemSignoffPackageError(Exception):
    """Base for every refusal in this module -- a real caller-usage error,
    never a silently-repaired input."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_name(name: Any) -> str:
    """A subsystem/precontract name, sanitized into a filesystem-safe bundle
    filename stem. Never invents a name for one that has none -- callers reach
    this only with a real (possibly caller-declared) name string."""
    cleaned = _SAFE_NAME_RE.sub("_", str(name)).strip("_")
    return cleaned or "unnamed"


def _derive_precontract_name(record: Any, index: int) -> str:
    """A caller-supplied subsystem-contract-shaped record's own declared
    identity -- `subsystem.resolved_name` first (a real registered name),
    then `subsystem.requested` (what was asked for, even if never registered).
    A record carrying neither is named positionally rather than guessed."""
    if isinstance(record, Mapping):
        subsystem = record.get("subsystem")
        if isinstance(subsystem, Mapping):
            for key in ("resolved_name", "requested"):
                value = subsystem.get(key)
                if value:
                    return str(value)
    return f"precontract_{index}"


def _record_manifest_entry(manifest: List[Dict[str, Any]], out_dir: Path,
                            artifact: str, present: bool,
                            bundled_rel: Optional[Path]) -> None:
    """The IDENTICAL manifest-entry shape `signoff_export.collect_signoff_
    bundle()`'s own private `record()` closure produces -- reproduced here
    rather than a second, differently-shaped one, so a system-scope
    manifest.json and a project-scope signoff_export manifest.json describe
    presence/content identically. Content identity reuses `signoff_export.
    _artifact_content_digest()` verbatim -- there is no second hasher in this
    module."""
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
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _assembled_gate_verified(contract: Mapping[str, Any]) -> bool:
    """A real, non-fabricated read of `signoff.stage.gate_verified` off one
    subsystem-contract-shaped record -- the same boolean `signoff_export.
    read_signoff_stage_status()` computed for that project (`stage_status ==
    SIGNOFF_VERIFIED_STATUS`). A malformed/absent shape reads False, never
    True -- an unproven gate must never default to passing."""
    signoff = contract.get("signoff") if isinstance(contract, Mapping) else None
    stage = signoff.get("stage") if isinstance(signoff, Mapping) else None
    return bool(stage.get("gate_verified")) if isinstance(stage, Mapping) else False


def _assemble_one_subsystem(root: Path, name: str, *, manifest_path: Optional[str],
                             requirements_path: Optional[str], db_path: Optional[str],
                             declared_spec_version: Optional[str]
                             ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(contract_or_None, error_text_or_None). Never lets a failure inside one
    subsystem's own real assembly crash the whole package -- exactly the same
    per-artifact honesty `collect_signoff_bundle()` already applies to every
    other candidate artifact it copies."""
    try:
        return sc.assemble_subsystem_contract(
            root, subsystem=name, manifest_path=manifest_path,
            requirements_path=requirements_path, db_path=db_path,
            declared_spec_version=declared_spec_version), None
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch in tests
        return None, f"{type(exc).__name__}: {exc}"


def collect_system_signoff_package(
        root, out_dir, *,
        subsystems: Optional[Sequence[str]] = None,
        subsystem_contracts: Optional[Sequence[Any]] = None,
        system_topology: Optional[Any] = None,
        system_resource_registry: Optional[Any] = None,
        system_command_registry: Optional[Any] = None,
        closure_dimensions: Optional[Sequence[Any]] = None,
        system_name: Optional[str] = None,
        manifest_path: Optional[str] = None,
        requirements_path: Optional[str] = None,
        db_path: Optional[str] = None,
        declared_spec_version: Optional[str] = None,
        require_system_signoff_pass: bool = False,
) -> Dict[str, Any]:
    """Assemble a system-scope signoff package under `out_dir`.

    `subsystems` -- names live-assembled by THIS module (one real
    `subsystem_contract.assemble_subsystem_contract(root, subsystem=name, ...)`
    call each). `subsystem_contracts` -- already-built subsystem-contract-
    shaped records a caller already holds (accepted duck-typed, exactly as
    `system_verification_contract.py`'s own `subsystem_contracts` parameter
    already is). Both may be combined; every subsystem, from either source, is
    bundled and reported in `subsystem_index`.

    Everything is assembled and the package_kind decided BEFORE anything is
    written, so `require_system_signoff_pass=True` can refuse (write nothing
    at all, not even an empty `out_dir`) exactly like `signoff_export.
    collect_signoff_bundle(require_signoff_pass=True)` already does.
    """
    root = Path(root).resolve()
    out_dir = Path(out_dir).resolve()

    assembled: List[Tuple[str, str, Optional[Dict[str, Any]], Optional[str]]] = []
    for name in (subsystems or ()):
        contract, error = _assemble_one_subsystem(
            root, name, manifest_path=manifest_path,
            requirements_path=requirements_path, db_path=db_path,
            declared_spec_version=declared_spec_version)
        assembled.append((str(name), SOURCE_LIVE_ASSEMBLED, contract, error))

    for idx, precontract in enumerate(subsystem_contracts or ()):
        name = _derive_precontract_name(precontract, idx)
        assembled.append((name, SOURCE_CALLER_SUPPLIED, precontract, None))

    real_contracts = [c for (_, _, c, _) in assembled if c is not None]

    sv_record = svc.assemble_system_verification_contract(
        subsystem_contracts=real_contracts or None,
        system_topology=system_topology,
        system_resource_registry=system_resource_registry,
        system_command_registry=system_command_registry,
        system_name=system_name)

    closure_report = sca.aggregate_system_closure(list(closure_dimensions or ()))

    all_subsystems_gate_verified = bool(real_contracts) and all(
        _assembled_gate_verified(c) for c in real_contracts)
    closure_closed = closure_report.get("overall_status") == sca.CLOSURE_CLOSED
    package_kind = (SYSTEM_SIGNOFF_GATE_VERIFIED
                    if (all_subsystems_gate_verified and closure_closed)
                    else PRE_SYSTEM_SIGNOFF_GATE_INPUT)

    subsystem_index_preview = [
        {"name": name, "source": source,
         "completeness": (contract or {}).get("completeness") if contract is not None else None,
         "gate_verified": _assembled_gate_verified(contract) if contract is not None else False,
         "error": error}
        for (name, source, contract, error) in assembled
    ]

    if require_system_signoff_pass and package_kind != SYSTEM_SIGNOFF_GATE_VERIFIED:
        return {
            "status": "REFUSED",
            "reason": "SYSTEM_SIGNOFF_NOT_VERIFIED",
            "detail": (
                f"package_kind would be {package_kind!r}, not "
                f"{SYSTEM_SIGNOFF_GATE_VERIFIED!r}: either not every assembled "
                f"subsystem's own real SIGNOFF stage gate has passed, or the system "
                f"closure rollup did not resolve CLOSED -- no gate-verified system "
                f"signoff package can be produced for this input."
            ),
            "out_dir": str(out_dir),
            "package_kind": package_kind,
            "manifest": [],
            "bundle_hash": None,
            "bundled_count": 0,
            "missing_count": 0,
            "system_verification_contract": sv_record,
            "system_closure_report": closure_report,
            "subsystem_index": subsystem_index_preview,
        }

    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, Any]] = []
    subsystem_index: List[Dict[str, Any]] = []
    used_stems: Dict[str, int] = {}

    for name, source, contract, error in assembled:
        stem = _safe_name(name)
        if source == SOURCE_CALLER_SUPPLIED:
            stem += "__supplied"
        seen = used_stems.get(stem, 0)
        used_stems[stem] = seen + 1
        if seen:
            stem = f"{stem}__{seen}"
        rel = Path("subsystems") / f"{stem}.json"
        artifact = f"subsystem_contract:{name}"
        if contract is not None:
            _write_json(out_dir, rel, contract)
            _record_manifest_entry(manifest, out_dir, artifact, True, rel)
            subsystem_index.append({
                "name": name, "source": source,
                "completeness": contract.get("completeness"),
                "gate_verified": _assembled_gate_verified(contract),
                "bundled_path": rel.as_posix(), "error": None,
            })
        else:
            _record_manifest_entry(manifest, out_dir, artifact, False, None)
            subsystem_index.append({
                "name": name, "source": source, "completeness": None,
                "gate_verified": False, "bundled_path": None, "error": error,
            })

    sv_rel = Path("system_verification_contract.json")
    _write_json(out_dir, sv_rel, sv_record)
    _record_manifest_entry(manifest, out_dir, "system_verification_contract", True, sv_rel)

    closure_rel = Path("system_closure_report.json")
    _write_json(out_dir, closure_rel, closure_report)
    _record_manifest_entry(manifest, out_dir, "system_closure_report", True, closure_rel)

    # The one function this whole module exists to REUSE rather than
    # reimplement -- see module docstring.
    bundle_hash = se.compute_bundle_hash(manifest)

    manifest_doc = {
        "schema_version": SCHEMA_VERSION,
        "assembled_at": _now_iso(),
        "system_name": system_name,
        "manifest": manifest,
        "bundle_hash": bundle_hash,
        "package_kind": package_kind,
        "subsystem_index": subsystem_index,
        "system_verification_completeness": sv_record.get("completeness"),
        "system_closure_status": closure_report.get("overall_status"),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    bundled_count = sum(1 for m in manifest if m["present"])
    missing_count = sum(1 for m in manifest if not m["present"])

    return {
        "status": "OK",
        "out_dir": str(out_dir),
        "manifest": manifest,
        "bundle_hash": bundle_hash,
        "bundled_count": bundled_count,
        "missing_count": missing_count,
        "package_kind": package_kind,
        "system_verification_contract": sv_record,
        "system_closure_report": closure_report,
        "subsystem_index": subsystem_index,
    }


# ---------------------------------------------------------------------------
# Rendering + CLI front door
# ---------------------------------------------------------------------------

def render_package_text(result: Dict[str, Any]) -> str:
    lines = [
        f"SYSTEM SIGNOFF PACKAGE: {result['status']}"
        + (f"  package_kind={result.get('package_kind')}" if result.get("package_kind") else ""),
    ]
    if result["status"] == "REFUSED":
        lines.append(f"  reason: {result.get('reason')}")
        lines.append(f"  detail: {result.get('detail')}")
        return "\n".join(lines)
    lines.append(f"  out_dir: {result['out_dir']}")
    lines.append(f"  bundle_hash: {result['bundle_hash']}")
    lines.append(f"  bundled={result['bundled_count']}  missing={result['missing_count']}")
    lines.append(f"  system_verification_contract: "
                 f"{result['system_verification_contract'].get('completeness')}")
    lines.append(f"  system_closure_report: "
                 f"{result['system_closure_report'].get('overall_status')}")
    lines.append(f"  subsystems ({len(result['subsystem_index'])}):")
    for entry in result["subsystem_index"]:
        lines.append(
            f"    - {entry['name']} [{entry['source']}]: "
            f"completeness={entry.get('completeness')} "
            f"gate_verified={entry.get('gate_verified')}"
            + (f"  ERROR={entry['error']}" if entry.get("error") else ""))
    return "\n".join(lines)


def _load_json_optional(path: Optional[str]) -> Optional[Any]:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise SystemSignoffPackageError(f"not a real file: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemSignoffPackageError(f"{p} is not valid JSON: {exc}") from exc


def _load_json_list(path: Optional[str], wrapper_key: str) -> List[Any]:
    data = _load_json_optional(path)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping) and isinstance(data.get(wrapper_key), list):
        return data[wrapper_key]
    raise SystemSignoffPackageError(
        f"{path} must contain a JSON array or {{{wrapper_key!r}: [...]}}, "
        f"got {type(data).__name__}")


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.system_signoff_package collect --root <dir>
    --out-dir <dir> [--subsystem NAME ...] [--subsystem-contracts <file>]
    [--topology <file>] [--resource-registry <file>] [--command-registry <file>]
    [--closure-dimensions <file>] [--system-name NAME]
    [--require-system-signoff-pass] [--json]`.

    Exit 0 SYSTEM_SIGNOFF_GATE_VERIFIED, 1 PRE_SYSTEM_SIGNOFF_GATE_INPUT,
    2 REFUSED or a usage error. No `dv-harness` CLI verb was added --
    `cli.py`/`gates.py` are out of this task's own file-safety scope."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="system-signoff-package",
        description="Assemble a system-scope signoff package from real "
                    "subsystem_contract.py records plus a "
                    "system_verification_contract.py rollup and a "
                    "system_closure_aggregator.py rollup, reusing "
                    "signoff_export.py's bundle-manifest mechanics.")
    ap.add_argument("verb", choices=["collect"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--out-dir", required=True, dest="out_dir")
    ap.add_argument("--subsystem", action="append", default=[], dest="subsystems",
                    help="a registered subsystem name to live-assemble "
                         "(repeatable).")
    ap.add_argument("--subsystem-contracts", default=None, dest="subsystem_contracts_path",
                    help="JSON file: a bare array, or "
                         "{'subsystem_contracts': [...]}, of already-built "
                         "subsystem_contract.py-shaped records.")
    ap.add_argument("--topology", default=None, dest="topology_path")
    ap.add_argument("--resource-registry", default=None, dest="resource_registry_path")
    ap.add_argument("--command-registry", default=None, dest="command_registry_path")
    ap.add_argument("--closure-dimensions", default=None, dest="closure_dimensions_path",
                    help="JSON file: a bare list of {dimension_name, status} "
                         "records, or {'dimensions': [...]}.")
    ap.add_argument("--system-name", default=None)
    ap.add_argument("--manifest", default=None, dest="manifest_path",
                    help="explicit env.manifest.json path for every "
                         "live-assembled subsystem.")
    ap.add_argument("--requirements", default=None, dest="requirements_path")
    ap.add_argument("--db", default=None, dest="db_path")
    ap.add_argument("--declared-spec-version", default=None)
    ap.add_argument("--require-system-signoff-pass", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    try:
        subsystem_contracts = _load_json_list(
            args.subsystem_contracts_path, "subsystem_contracts")
        system_topology = _load_json_optional(args.topology_path)
        system_resource_registry = _load_json_optional(args.resource_registry_path)
        system_command_registry = _load_json_optional(args.command_registry_path)
        closure_dimensions = _load_json_list(args.closure_dimensions_path, "dimensions")

        result = collect_system_signoff_package(
            args.root, args.out_dir,
            subsystems=args.subsystems or None,
            subsystem_contracts=subsystem_contracts or None,
            system_topology=system_topology,
            system_resource_registry=system_resource_registry,
            system_command_registry=system_command_registry,
            closure_dimensions=closure_dimensions,
            system_name=args.system_name,
            manifest_path=args.manifest_path,
            requirements_path=args.requirements_path,
            db_path=args.db_path,
            declared_spec_version=args.declared_spec_version,
            require_system_signoff_pass=args.require_system_signoff_pass)
    except SystemSignoffPackageError as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
          else render_package_text(result))

    if result["status"] == "REFUSED":
        return 2
    return 0 if result["package_kind"] == SYSTEM_SIGNOFF_GATE_VERIFIED else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys
    return execute_verb(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    import sys
    sys.exit(main())
