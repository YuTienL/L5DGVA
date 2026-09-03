"""dv_harness/env_manifest.py -- generator for env.manifest.json, a
generated, diffable, git-tracked fact file with exactly three top-level
layers (Part A of the 2026-09-03 env.manifest.json + MCP + question-queue
spec):

  vip_config   -- three VIP fact sources: the VIP's own already-resolved
                  config object as a real UVM simv would dump it via a
                  zero-time end_of_elaboration_phase callback (see
                  dv_harness/uvm_generator/templates/uvm_env_manifest/
                  dv_env_manifest_pkg.sv for the generic template code a
                  generated environment includes to produce that dump);
                  `vip_release`, from a REAL filesystem scan of
                  $DESIGNWARE_HOME, answering which VIP release this
                  environment is actually built against from the install
                  tree rather than from a version someone typed into a
                  document; and `user_guide_refs`, POINTERS to user guides
                  distilled OFFLINE by dv_harness/vip_user_guide_distill.py.
  dut_facts    -- ports/params/signals reverse-derived from real verible
                  --export_json RTL parsing (extends
                  dv_harness/verible_parser.py's own parse_file()/to_dict()
                  output -- this module does NOT re-implement RTL parsing),
                  registers read from a structured RAL/IP-XACT-style input
                  file (dv_harness/schemas/register_map.schema.json), and
                  `address_map`/`clock_reset` from the project's own SoC
                  spec pipeline (dv_harness/schemas/soc_arch_map.schema.json).
                  Every address_map entry additionally carries a real
                  cross-check against the register map's own base addresses.
  env_topology -- component hierarchy + config_db set/get trace, captured
                  from a real uvm_top run (see the same template package
                  for the hierarchy-dump mechanism; +UVM_CONFIG_DB_TRACE is
                  a native UVM plusarg needing no template code), plus
                  `testplan_correspondence`, the computed three-way join of
                  the project's real testlist, vPlan items and coverage
                  model (dv_harness/schemas/testplan_sources.schema.json).

The three fact sources added on 2026-09-04 -- vip_release, user_guide_refs,
address_map/clock_reset, testplan_correspondence -- were confirmed BLOCKED by
a re-audit that day (no DESIGNWARE_HOME reader anywhere in dv_harness/, no
user-guide distiller at all, no address-map/clock-reset field in the schema,
zero testlist/vPlan/coverage hits in this module). Each closure's own
rationale sits above its builder rather than being restated here.

SCHEMA VERSION. Those additions took the schema from 1.0 to 1.1, and they
are REQUIRED keys: this module is the manifest's sole writer, so a manifest
that predates them is regenerated rather than migrated. A stale 1.0 file on
disk therefore fails load_env_manifest() loudly instead of silently
presenting an environment as having no address map and no testplan
correspondence, which is a claim about the environment it cannot support.

Every layer that requires a real captured artifact (a VIP config dump, a
topology dump, a config_db trace log) reports status="NOT_AVAILABLE" with an
honest `reason` when that artifact does not exist yet -- this module never
fabricates example VIP config, topology, or register content for a project
it has not actually observed. This mirrors the same discipline already
established in this repo by memory_vault.py's ObsidianAdapter (see
docs/MEMORY_ARCHITECTURE.md) and verible_parser.py's own real-tool-or-
explicit-error contract.

Those NOT_AVAILABLE results distinguish two genuinely different situations,
because collapsing them hides a real, actionable operator error: "no path
was supplied at all" reports source.path=None with the 'no <artifact> exists
yet' reason, while "a path WAS supplied but does not exist" reports the real
supplied path in source.path with a 'supplied ... path does not exist:
<path>' reason, so a typo'd/stale --vip-config-dump argument stays traceable
in the manifest instead of being silently discarded. This is the same
honesty standard build_dut_facts_rtl() already applies by letting a real
parse failure against a real supplied file propagate rather than
downgrading it to NOT_AVAILABLE.

Diffability: save_env_manifest() writes deterministic key order (this
module builds every dict in a fixed field order, never sort_keys=True,
which would reorder e.g. dut_facts.rtl.files[].modules[].ports[] entries
away from their real source-file declaration order) and pretty-printed
JSON with a trailing newline. There is deliberately no "generated_at"
timestamp field anywhere in the schema -- regenerating this file from
unchanged real inputs must produce a byte-identical file, so a real diff
always means a real underlying change, never clock noise.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import verible_parser

SCHEMA_VERSION = "1.1"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "env_manifest.schema.json"
REGISTER_MAP_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "register_map.schema.json"
SOC_ARCH_MAP_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "soc_arch_map.schema.json"
TESTPLAN_SOURCES_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "testplan_sources.schema.json"


class EnvManifestValidationError(ValueError):
    """env.manifest.json (or a dict about to become one) fails schema
    validation. Raised instead of returning False/None so a caller cannot
    accidentally persist or consume an invalid manifest -- the same
    fail-closed discipline as run_profile.py's RunProfileValidationError."""


class RegisterMapValidationError(ValueError):
    """A register-map input file fails register_map.schema.json validation
    -- e.g. malformed hex, a missing required field. Raised rather than
    silently dropping the bad entries, since dut_facts.registers must never
    report LOADED against content that did not actually validate."""


class SocArchMapValidationError(ValueError):
    """A SoC architecture-map input file fails soc_arch_map.schema.json
    validation -- e.g. a reset with no `active_level`, a malformed hex base.
    Same fail-closed reasoning as RegisterMapValidationError: dut_facts.
    address_map / dut_facts.clock_reset must never report LOADED against
    content that did not actually validate."""


class TestplanSourcesValidationError(ValueError):
    """A testplan-sources input file fails testplan_sources.schema.json
    validation. Raised rather than computing a correspondence over partially
    understood input, because a correspondence report's whole value is that
    its "missing"/"orphan" lists are trustworthy -- one silently dropped
    malformed entry turns a real link into a fabricated break, or vice
    versa."""


def _load_json_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_against(doc: dict, schema_path: Path, error_cls) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise error_cls(
            f"jsonschema package is not installed; cannot validate against {schema_path.name}. "
            "Install it rather than skipping validation."
        ) from exc
    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise error_cls(f"{schema_path.name} validation failed:\n" + "\n".join(lines))


def validate_env_manifest(manifest: dict) -> None:
    """Validate `manifest` against env_manifest.schema.json. Raises
    EnvManifestValidationError on any violation."""
    _validate_against(manifest, SCHEMA_PATH, EnvManifestValidationError)


def validate_register_map(doc: dict) -> None:
    """Validate a register-map input document against
    register_map.schema.json. Raises RegisterMapValidationError on any
    violation."""
    _validate_against(doc, REGISTER_MAP_SCHEMA_PATH, RegisterMapValidationError)


def validate_soc_arch_map(doc: dict) -> None:
    """Validate a SoC architecture-map input document against
    soc_arch_map.schema.json. Raises SocArchMapValidationError."""
    _validate_against(doc, SOC_ARCH_MAP_SCHEMA_PATH, SocArchMapValidationError)


def validate_testplan_sources(doc: dict) -> None:
    """Validate a testplan-sources input document against
    testplan_sources.schema.json. Raises TestplanSourcesValidationError."""
    _validate_against(doc, TESTPLAN_SOURCES_SCHEMA_PATH, TestplanSourcesValidationError)


def load_env_manifest(path) -> dict:
    """Load and validate an env.manifest.json from disk. Raises
    EnvManifestValidationError if the file is not schema-valid -- a caller
    (an MCP verb, an agent-facing query) must never consume an unvalidated
    manifest."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_env_manifest(manifest)
    return manifest


def save_env_manifest(manifest: dict, path) -> None:
    """Validate then write `manifest` to `path` as deterministic,
    pretty-printed JSON (see module docstring's Diffability section)."""
    validate_env_manifest(manifest)
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# dut_facts.rtl -- extends verible_parser.py, never re-parses RTL itself
# ---------------------------------------------------------------------------

def build_dut_facts_rtl(rtl_files, verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN) -> dict:
    """`rtl_files`: an iterable of real RTL file paths. Runs
    verible_parser.parse_file()/to_dict() (unmodified) against each and
    folds the results into dut_facts.rtl's shape, sorted by file_path for a
    stable diff. Raises VeribleUnavailableError/VeribleParseError straight
    through (a real parse failure against a real supplied file is a real
    error, never silently downgraded to NOT_AVAILABLE -- NOT_AVAILABLE is
    reserved for 'no capture attempted at all', per this module's own
    honesty contract).

    An empty `rtl_files` is NOT an error -- it means no RTL source was
    supplied to this generation run, reported as NOT_AVAILABLE with an
    honest reason, same as the other two layers."""
    paths = [Path(p) for p in (rtl_files or [])]
    if not paths:
        return {"status": "NOT_AVAILABLE", "reason": "no rtl_files supplied to this generation run", "files": []}
    files = []
    for p in paths:
        result = verible_parser.parse_file(p, verible_bin=verible_bin)
        files.append(verible_parser.to_dict(result))
    files.sort(key=lambda f: f["file_path"])
    return {"status": "PARSED", "reason": None, "files": files}


# ---------------------------------------------------------------------------
# dut_facts.registers -- structured input contract, never invented content
# ---------------------------------------------------------------------------

def load_register_map(path) -> dict:
    """Load and validate a register-map input file against
    register_map.schema.json (dv_harness/schemas/register_map.schema.json
    is the documented input contract -- a real RAL model export, an IP-XACT
    conversion, or a transcription from a real programming guide; never
    content this harness invented). Raises RegisterMapValidationError if
    the file does not conform."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_register_map(doc)
    return doc


def build_dut_facts_registers(register_map_path=None) -> dict:
    if register_map_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "register_map_json", "path": None},
            "reason": "no register-map input file supplied -- see dv_harness/schemas/register_map.schema.json "
                      "for the expected input contract (a real RAL model export or IP-XACT conversion, "
                      "never harness-invented register content)",
            "blocks": [],
        }
    doc = load_register_map(register_map_path)
    return {
        "status": "LOADED",
        "source": {"kind": "register_map_json", "path": str(register_map_path)},
        "reason": None,
        "blocks": doc.get("blocks", []),
    }


# ---------------------------------------------------------------------------
# dut_facts.address_map / dut_facts.clock_reset -- the SoC-spec-pipeline
# fact source (2026-09-04).
#
# THE GAP THIS CLOSES. The spec's DUT layer asks for the address map and the
# clock/reset topology to come from the existing SoC spec pipeline. A
# 2026-09-04 re-audit found `dut_facts` carried exactly two sub-keys (`rtl`,
# `registers`) with no field for either, and `grep -n "address_map\|
# clock_reset" dv_harness/env_manifest.py` returning nothing. The pieces
# existed elsewhere and were never plumbed in:
# `uvm_generator/address_map_verifier.py` is a real 3-source-corroboration
# verifier, and `generated/01_architecture/clock_reset_map/` is a real
# pipeline output directory -- but that directory is EMPTY in this repo, and
# nothing imported the verifier from here.
#
# WHY AN INPUT CONTRACT AND NOT AN EXTRACTOR. dv_harness is the meta-harness
# and owns no SoC, so there is nothing here to extract FROM; an "extractor"
# would have to invent architecture, which the Evidence Truth Rule forbids.
# So this follows register_map.schema.json's already-established precedent
# exactly: a documented input contract (soc_arch_map.schema.json) that a
# real project's own SoC spec pipeline exports to, read and validated here
# and never authored here.
#
# WHAT THIS ADDS BEYOND PASSTHROUGH -- and it is the reason the layer earns
# its place next to `registers` rather than living in its own file: the two
# fact sources describe OVERLAPPING reality. A register map and an address
# map both claim a base address per block. Carrying both without comparing
# them is how an environment ends up with a decoder at one base and a RAL
# model at another, each internally consistent. Every entry therefore gets a
# real `register_map_agreement` computed against dut_facts.registers, and a
# DISAGREES is surfaced for a human -- never resolved here by whichever
# source happened to load last, per CLAUDE.md's Source Authority Order.
# ---------------------------------------------------------------------------

def load_soc_arch_map(path) -> dict:
    """Load and validate a SoC architecture-map input file against
    soc_arch_map.schema.json. Raises SocArchMapValidationError."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_soc_arch_map(doc)
    return doc


def _hex_int(value):
    """Parse a schema-validated '0x...' base address to an int. The schema's
    own pattern already guarantees the form, so a failure here is a real
    programming error, not user input to be tolerated."""
    return int(value, 16)


def build_dut_facts_address_map(soc_arch_map_path=None, registers_layer=None) -> dict:
    """`registers_layer` is this same manifest's already-built
    dut_facts.registers, used ONLY to compute register_map_agreement -- it is
    never modified, and never overrides an address-map value."""
    if soc_arch_map_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "soc_arch_map_json", "path": None},
            "reason": "no SoC architecture-map input file supplied -- see "
                      "dv_harness/schemas/soc_arch_map.schema.json for the expected input contract "
                      "(a real SoC spec pipeline export or IP-XACT memory-map conversion, never "
                      "harness-invented architecture)",
            "entries": [],
            "disagreement_count": 0,
        }
    doc = load_soc_arch_map(soc_arch_map_path)
    raw = doc.get("address_map")
    if raw is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "soc_arch_map_json", "path": str(soc_arch_map_path)},
            "reason": f"supplied SoC architecture map carries no 'address_map' key: {soc_arch_map_path}",
            "entries": [],
            "disagreement_count": 0,
        }

    # Cross-check index, built from the REAL register map only when one was
    # actually loaded. "no register map to compare against" and "compared,
    # and this block is absent from it" are different findings and stay
    # different in the output.
    registers_layer = registers_layer or {}
    have_registers = registers_layer.get("status") == "LOADED"
    reg_bases = {}
    if have_registers:
        for block in registers_layer.get("blocks") or []:
            name = block.get("name")
            base = block.get("base_address")
            if name is not None and base is not None:
                reg_bases[name] = _hex_int(base)

    entries = []
    disagreements = 0
    for e in raw:
        if not have_registers:
            agreement = "NOT_AVAILABLE"
        elif e["name"] not in reg_bases:
            agreement = "NOT_IN_REGISTER_MAP"
        elif reg_bases[e["name"]] == _hex_int(e["base_address"]):
            agreement = "AGREES"
        else:
            agreement = "DISAGREES"
            disagreements += 1
        entries.append({
            "name": e["name"],
            "base_address": e["base_address"],
            "size_bytes": e["size_bytes"],
            "target": e.get("target"),
            "bus": e.get("bus"),
            "evidence": e.get("evidence"),
            "description": e.get("description"),
            "register_map_agreement": agreement,
        })
    entries.sort(key=lambda x: (_hex_int(x["base_address"]), x["name"]))
    return {
        "status": "LOADED",
        "source": {"kind": "soc_arch_map_json", "path": str(soc_arch_map_path)},
        "reason": None,
        "entries": entries,
        "disagreement_count": disagreements,
    }


def build_dut_facts_clock_reset(soc_arch_map_path=None) -> dict:
    if soc_arch_map_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "soc_arch_map_json", "path": None},
            "reason": "no SoC architecture-map input file supplied -- see "
                      "dv_harness/schemas/soc_arch_map.schema.json for the expected input contract",
            "clocks": [],
            "resets": [],
        }
    doc = load_soc_arch_map(soc_arch_map_path)
    raw_clocks = doc.get("clocks")
    raw_resets = doc.get("resets")
    if raw_clocks is None and raw_resets is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "soc_arch_map_json", "path": str(soc_arch_map_path)},
            "reason": f"supplied SoC architecture map carries neither 'clocks' nor 'resets': "
                      f"{soc_arch_map_path}",
            "clocks": [],
            "resets": [],
        }
    clocks = sorted(
        [{"name": c["name"], "frequency_mhz": c.get("frequency_mhz"), "source": c.get("source"),
          "domain": c.get("domain"), "evidence": c.get("evidence"), "description": c.get("description")}
         for c in (raw_clocks or [])],
        key=lambda c: c["name"],
    )
    clock_names = {c["name"] for c in clocks}
    resets = []
    for r in (raw_resets or []):
        clock = r.get("clock")
        if clock is None:
            resolved = "NOT_SPECIFIED"
        elif clock in clock_names:
            resolved = "RESOLVED"
        else:
            # A reset synchronised to a clock the same document never
            # declares is a real inconsistency in the input. Surfacing it
            # beats carrying it silently: a testbench built against a
            # clock name that does not exist fails late and confusingly.
            resolved = "UNKNOWN_CLOCK"
        resets.append({
            "name": r["name"], "active_level": r["active_level"],
            "synchronous": r.get("synchronous"), "clock": clock,
            "clock_resolved": resolved,
            "evidence": r.get("evidence"), "description": r.get("description"),
        })
    resets.sort(key=lambda r: r["name"])
    return {
        "status": "LOADED",
        "source": {"kind": "soc_arch_map_json", "path": str(soc_arch_map_path)},
        "reason": None,
        "clocks": clocks,
        "resets": resets,
    }


def build_dut_facts(rtl_files=None, register_map_path=None,
                     verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
                     soc_arch_map_path=None) -> dict:
    registers = build_dut_facts_registers(register_map_path)
    return {
        "rtl": build_dut_facts_rtl(rtl_files, verible_bin=verible_bin),
        "registers": registers,
        "address_map": build_dut_facts_address_map(soc_arch_map_path, registers_layer=registers),
        "clock_reset": build_dut_facts_clock_reset(soc_arch_map_path),
    }


# ---------------------------------------------------------------------------
# vip_config -- parses a real dump produced by dv_env_manifest_pkg.sv;
# honest NOT_AVAILABLE when no dump exists yet (never a fabricated example)
# ---------------------------------------------------------------------------

def parse_vip_config_dump(path) -> list:
    """Reads a real vip_config dump JSON file (the shape
    dv_env_manifest_write_vip_config_dump() in dv_env_manifest_pkg.sv
    writes: {"schema_version": "1.0", "vip_instances": [{"instance_path",
    "vip_type", "config_fields"}, ...]}) and returns the vip_instances list,
    sorted by instance_path for a stable diff. Raises ValueError if the
    dump's own top-level shape is not what the template produces -- a
    malformed dump is a real error, never silently treated as empty."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    instances = doc.get("vip_instances")
    if instances is None:
        raise ValueError(f"{path}: vip_config dump is missing 'vip_instances'")
    for entry in instances:
        for required in ("instance_path", "vip_type", "config_fields"):
            if required not in entry:
                raise ValueError(f"{path}: vip_config dump entry missing required field {required!r}: {entry!r}")
    return sorted(instances, key=lambda e: e["instance_path"])


def build_vip_config(dump_path=None) -> dict:
    if dump_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "vip_config_dump_json", "path": None},
            "reason": "no VIP config dump exists yet for this environment -- requires a live UVM simv run "
                      "with +VIP_CONFIG_DUMP_PATH=<path> (see dv_harness/uvm_generator/templates/"
                      "uvm_env_manifest/dv_env_manifest_pkg.sv)",
            "vip_instances": [],
        }
    if not Path(dump_path).is_file():
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "vip_config_dump_json", "path": str(dump_path)},
            "reason": f"supplied VIP config dump path does not exist: {dump_path}",
            "vip_instances": [],
        }
    instances = parse_vip_config_dump(dump_path)
    return {
        "status": "CAPTURED",
        "source": {"kind": "vip_config_dump_json", "path": str(dump_path)},
        "reason": None,
        "vip_instances": instances,
    }


# ---------------------------------------------------------------------------
# vip_config.vip_release -- a REAL filesystem scan of $DESIGNWARE_HOME
# (2026-09-04). The spec's VIP layer asks for the VIP's version, release
# notes and feature matrix to come from the install tree plus its version
# files. A 2026-09-04 re-audit found no code anywhere in dv_harness/ reading
# DESIGNWARE_HOME (the single repo-wide hit was an unrelated env-var name in
# an allow-list inside templates/sim_scripts/check/make_order.py), and no
# schema field to put the answer in -- a genuinely BLOCKED bullet.
#
# WHY A SCAN AND NOT A DECLARED VERSION FIELD. "Which VIP release is this
# environment actually built against" has exactly one trustworthy answer:
# what is on disk under the DESIGNWARE_HOME this run would really compile
# against. A version string typed into a document or a config file is a
# claim about the install, not the install -- the same reasoning that makes
# the zero-time config dump above more trustworthy than a user guide.
#
# WHAT IS DELIBERATELY NOT DONE: release-notes and feature-matrix files are
# recorded as path + sha256 + size, never read into the manifest. They are
# vendor documents of unbounded length, and env.manifest.json is a TIER-2
# ALWAYS-RESIDENT artifact under CLAUDE.md's Context Budget -- inlining one
# would push a vendor changelog into every session's context in perpetuity.
# ---------------------------------------------------------------------------

import os

DESIGNWARE_HOME_ENV = "DESIGNWARE_HOME"

#: Relative roots under $DESIGNWARE_HOME where `dw_vip_setup` really lands
#: installed VIP packages, in the two layouts it has used. Both are scanned
#: as `<root>/<package>/<version>`; a package found under more than one root
#: is recorded once, keyed by its real install path.
_DESIGNWARE_VIP_ROOTS = ("vip/svt", "vip")

#: Filename fragments (lower-cased substring match) that identify a real
#: release-notes / feature-matrix document inside an installed VIP package.
#: Substring rather than exact name because vendors version and prefix these
#: files per package (`usb_svt_release_notes.txt`, `ReleaseNotes.html`, ...);
#: an exact-name list would silently find nothing on a real install.
_RELEASE_NOTES_FRAGMENTS = ("release_note", "releasenote", "relnotes", "rel_notes")
_FEATURE_MATRIX_FRAGMENTS = ("feature_matrix", "featurematrix", "feature-matrix")

#: How deep inside a VIP version directory to look for those documents.
#: Bounded because a real VIP install is a very large tree and this scan
#: must stay cheap enough to run on every `env-manifest generate`.
_VIP_DOC_SCAN_MAX_DEPTH = 3


def _file_ref(path) -> dict:
    """A doc_file_ref for a real file: path + sha256 + real byte size, never
    content. `path=None` (the file genuinely does not exist -- e.g. a VIP
    package that ships no feature matrix) yields an all-null ref rather than
    an omitted key, so "looked, and there is none" stays visible."""
    if path is None:
        return {"path": None, "sha256": None, "bytes": None}
    p = Path(path)
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return {"path": str(p), "sha256": h.hexdigest(), "bytes": p.stat().st_size}


def _find_doc_in_package(install_path: Path, fragments) -> Optional[Path]:
    """First real file under `install_path` (bounded to
    _VIP_DOC_SCAN_MAX_DEPTH levels) whose lower-cased name contains any of
    `fragments`. Deterministic: candidates are sorted by their path string
    before the first is taken, so a package shipping several release-notes
    files always yields the same one into a diffable manifest."""
    matches = []
    base_depth = len(install_path.parts)
    for dirpath, dirnames, filenames in os.walk(install_path):
        here = Path(dirpath)
        if len(here.parts) - base_depth >= _VIP_DOC_SCAN_MAX_DEPTH:
            dirnames[:] = []
        for fn in filenames:
            low = fn.lower()
            if any(frag in low for frag in fragments):
                matches.append(here / fn)
    if not matches:
        return None
    return sorted(matches, key=lambda p: str(p))[0]


def scan_designware_home(designware_home) -> list:
    """Walk a REAL DesignWare install tree and return one record per
    installed VIP package/version directory actually found, sorted by
    (name, version) for a stable diff.

    A package directory containing no version sub-directory is recorded with
    `version=None` -- never a guessed or synthesised version string. An
    empty return is a real finding ("this DESIGNWARE_HOME contains no
    recognisable VIP package"), not an error."""
    home = Path(designware_home)
    # The two layouts nest: `vip` CONTAINS `vip/svt`. Without this, scanning
    # the `vip` root would report the `svt` directory itself as a package
    # named "svt" whose "versions" are the real package names -- a wrong
    # answer that still looks structurally plausible in the manifest.
    root_dirs = {(home / rel).resolve() for rel in _DESIGNWARE_VIP_ROOTS}
    packages = {}
    for rel in _DESIGNWARE_VIP_ROOTS:
        root = home / rel
        if not root.is_dir():
            continue
        for pkg_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if pkg_dir.resolve() in root_dirs:
                continue
            version_dirs = sorted(v for v in pkg_dir.iterdir() if v.is_dir())
            targets = [(pkg_dir.name, v.name, v) for v in version_dirs] or [(pkg_dir.name, None, pkg_dir)]
            for name, version, install in targets:
                key = str(install.resolve())
                if key in packages:
                    continue
                packages[key] = {
                    "name": name,
                    "version": version,
                    "install_path": str(install),
                    "release_notes": _file_ref(_find_doc_in_package(install, _RELEASE_NOTES_FRAGMENTS)),
                    "feature_matrix": _file_ref(_find_doc_in_package(install, _FEATURE_MATRIX_FRAGMENTS)),
                }
    return sorted(packages.values(), key=lambda p: (p["name"], p["version"] or ""))


def build_vip_release(designware_home=None) -> dict:
    """`designware_home`: an explicit path, or None to read the real
    $DESIGNWARE_HOME environment variable.

    Three honestly-distinct outcomes, for the same reason build_vip_config()
    distinguishes "no path supplied" from "supplied path missing": an unset
    DESIGNWARE_HOME and a DESIGNWARE_HOME pointing at a stale/typo'd path are
    different operator situations, and collapsing them hides a real, fixable
    mistake behind a generic "not available"."""
    resolved = designware_home if designware_home is not None else os.environ.get(DESIGNWARE_HOME_ENV)
    if not resolved:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "designware_home_scan", "path": None},
            "reason": f"${DESIGNWARE_HOME_ENV} is not set and no explicit path was supplied -- no VIP install "
                      "tree to scan, so no VIP version/release-notes/feature-matrix facts exist for this "
                      "environment yet",
            "designware_home": None,
            "packages": [],
        }
    if not Path(resolved).is_dir():
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "designware_home_scan", "path": str(resolved)},
            "reason": f"${DESIGNWARE_HOME_ENV} is set to a path that is not an existing directory: {resolved}",
            "designware_home": str(resolved),
            "packages": [],
        }
    return {
        "status": "SCANNED",
        "source": {"kind": "designware_home_scan", "path": str(resolved)},
        "reason": None,
        "designware_home": str(resolved),
        "packages": scan_designware_home(resolved),
    }


# ---------------------------------------------------------------------------
# vip_config.user_guide_refs -- POINTERS to offline-distilled user guides
# (2026-09-04). See dv_harness/vip_user_guide_distill.py, which is the ONLY
# module that ever opens the source document, and which runs as its own
# `dv-harness vip-user-guide distill` command. This layer reads only the
# small `.reference.json` record that command leaves behind, so a manifest
# generation run structurally CANNOT pull a user guide's text into context.
# ---------------------------------------------------------------------------

#: Keys that would mean document CONTENT had leaked into the manifest.
#: assert_no_user_guide_body_in_manifest() rejects any of them appearing
#: anywhere under vip_config.user_guide_refs.
_FORBIDDEN_BODY_KEYS = frozenset({
    "content", "text", "body", "full_text", "fulltext", "excerpt", "sections", "headings", "pages",
})

#: Longest string tolerated anywhere under user_guide_refs. Comfortably
#: above any real path/sha256/title, and far below any real paragraph.
_MAX_USER_GUIDE_STRING_CHARS = 1024


def build_user_guide_refs(reference_record_paths=None) -> dict:
    """`reference_record_paths`: paths to `.reference.json` records produced
    by `dv-harness vip-user-guide distill`. Returns the manifest's
    user_guide_refs layer: pointers only, sorted by title for a stable
    diff."""
    paths = list(reference_record_paths or [])
    if not paths:
        return {
            "status": "NOT_AVAILABLE",
            "reason": "no VIP user guide has been distilled for this environment yet -- run "
                      "`dv-harness vip-user-guide distill --source <guide.pdf> --out-dir <dir>` "
                      "(an OFFLINE step; see dv_harness/vip_user_guide_distill.py) and pass the "
                      "resulting .reference.json here",
            "documents": [],
        }
    from . import vip_user_guide_distill
    documents = []
    for p in paths:
        record = vip_user_guide_distill.load_reference_record(p)
        src = record["source_document"]
        documents.append({
            "title": record["title"],
            "doc_kind": record["doc_kind"],
            "source_document": {
                "path": src.get("path"), "sha256": src.get("sha256"),
                "bytes": src.get("bytes"), "page_count": src.get("page_count"),
            },
            "distilled_reference": {
                "path": record["distilled_reference"].get("path"),
                "sha256": record["distilled_reference"].get("sha256"),
                "bytes": record["distilled_reference"].get("bytes"),
            },
            "full_text_extract": {
                "path": record["full_text_extract"].get("path"),
                "sha256": record["full_text_extract"].get("sha256"),
                "bytes": record["full_text_extract"].get("bytes"),
            },
            "extraction": {
                "tool": record["extraction"].get("tool"),
                "tool_version": record["extraction"].get("tool_version"),
                "method": record["extraction"].get("method"),
            },
            "section_count": record["section_count"],
        })
    documents.sort(key=lambda d: d["title"])
    return {"status": "INDEXED", "reason": None, "documents": documents}


def assert_no_user_guide_body_in_manifest(manifest: dict) -> None:
    """Make "never loaded into runtime context" a CHECKABLE property rather
    than a promise, in the same spirit as vip_symbol_index.
    assert_no_bodies_retained().

    Raises EnvManifestValidationError if anything under
    vip_config.user_guide_refs looks like document content: a key from
    _FORBIDDEN_BODY_KEYS, or any string longer than
    _MAX_USER_GUIDE_STRING_CHARS. Both checks matter -- the schema's
    additionalProperties:false already blocks a *new* key at a level it
    describes, but it cannot notice a paragraph of prose smuggled into a
    field that is legitimately a string."""
    layer = ((manifest or {}).get("vip_config") or {}).get("user_guide_refs")
    if layer is None:
        return

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() in _FORBIDDEN_BODY_KEYS:
                    raise EnvManifestValidationError(
                        f"vip_config.user_guide_refs{path}: key {k!r} would carry user-guide CONTENT into "
                        "env.manifest.json, which is a TIER-2 always-resident artifact. This layer records "
                        "pointers (path/sha256/bytes/counts) only -- the content stays in the offline "
                        "distiller's own output files."
                    )
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and len(node) > _MAX_USER_GUIDE_STRING_CHARS:
            raise EnvManifestValidationError(
                f"vip_config.user_guide_refs{path}: string of {len(node)} chars exceeds the "
                f"{_MAX_USER_GUIDE_STRING_CHARS}-char pointer budget -- this looks like document prose, not a "
                "path/hash/title."
            )

    walk(layer, "")


def build_vip_config_layer(dump_path=None, designware_home=None,
                            user_guide_reference_paths=None) -> dict:
    """Assemble the whole vip_config layer: the zero-time config dump, the
    real $DESIGNWARE_HOME release scan, and the offline-distilled user-guide
    pointers -- the spec's three VIP fact sources."""
    layer = build_vip_config(dump_path)
    layer["vip_release"] = build_vip_release(designware_home)
    layer["user_guide_refs"] = build_user_guide_refs(user_guide_reference_paths)
    return layer


# ---------------------------------------------------------------------------
# env_topology.component_hierarchy -- parses a real dump produced by
# dv_env_manifest_pkg.sv's dv_env_manifest_write_topology_dump()
# ---------------------------------------------------------------------------

def parse_topology_dump(path) -> list:
    """Reads a real component_hierarchy dump JSON file and returns its
    components list, sorted by full_name for a stable diff."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    components = doc.get("components")
    if components is None:
        raise ValueError(f"{path}: topology dump is missing 'components'")
    for entry in components:
        for required in ("full_name", "type_name", "is_active"):
            if required not in entry:
                raise ValueError(f"{path}: topology dump entry missing required field {required!r}: {entry!r}")
    return sorted(components, key=lambda c: c["full_name"])


def build_component_hierarchy(dump_path=None) -> dict:
    if dump_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "topology_dump_json", "path": None},
            "reason": "no component_hierarchy dump exists yet for this environment -- requires a live UVM "
                      "simv run with +ENV_TOPOLOGY_DUMP_PATH=<path> (see dv_harness/uvm_generator/templates/"
                      "uvm_env_manifest/dv_env_manifest_pkg.sv)",
            "components": [],
        }
    if not Path(dump_path).is_file():
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "topology_dump_json", "path": str(dump_path)},
            "reason": f"supplied component_hierarchy dump path does not exist: {dump_path}",
            "components": [],
        }
    components = parse_topology_dump(dump_path)
    return {
        "status": "CAPTURED",
        "source": {"kind": "topology_dump_json", "path": str(dump_path)},
        "reason": None,
        "components": components,
    }


# ---------------------------------------------------------------------------
# env_topology.config_db_trace -- parses a real +UVM_CONFIG_DB_TRACE sim
# log. Only the UVM_INFO report ENVELOPE (file/line/time/reporter/id) is a
# stable, documented format and is fully parsed; the message BODY's own
# internal field/value sub-format has never been verified against a live
# UVM run in this repo and is deliberately kept OPAQUE rather than guessed
# apart -- see parse_confidence in env_manifest.schema.json.
# ---------------------------------------------------------------------------

import re

_UVM_INFO_LINE_RE = re.compile(
    r"^UVM_INFO\s+(?P<file>\S+)\((?P<line>\d+)\)\s*@\s*(?P<time>[^:]+):\s*(?P<reporter>\S+)\s*"
    r"\[(?P<id>[^\]]+)\]\s*(?P<message>.*)$"
)


def parse_config_db_trace_log(text: str) -> list:
    """Best-effort, single-physical-line extraction of +UVM_CONFIG_DB_TRACE
    report lines from a real sim log's raw text. Only lines whose message
    id is exactly CFGDB/SET or CFGDB/GET are kept (the config_db tracing
    feature's own report id -- everything else in the log is real UVM
    traffic this function is not asked to interpret). A multi-line UVM
    message (rare for config_db trace, but possible in general) is NOT
    reassembled -- only the first physical line is captured, since this
    repo has never observed a real live UVM run's actual continuation-line
    formatting to build that logic against with confidence."""
    entries = []
    for line in text.splitlines():
        m = _UVM_INFO_LINE_RE.match(line.strip())
        if not m:
            continue
        msg_id = m.group("id").strip()
        if msg_id == "CFGDB/SET":
            kind = "SET"
        elif msg_id == "CFGDB/GET":
            kind = "GET"
        else:
            continue
        entries.append({
            "kind": kind,
            "file": m.group("file"),
            "line": int(m.group("line")),
            "time": m.group("time").strip(),
            "reporter": m.group("reporter"),
            "message": m.group("message"),
        })
    return entries


def build_config_db_trace(log_path=None) -> dict:
    if log_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "sim_log_uvm_config_db_trace", "path": None},
            "reason": "no sim log with +UVM_CONFIG_DB_TRACE exists yet for this environment",
            "parse_confidence": None,
            "entries": [],
        }
    if not Path(log_path).is_file():
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "sim_log_uvm_config_db_trace", "path": str(log_path)},
            "reason": f"supplied +UVM_CONFIG_DB_TRACE sim log path does not exist: {log_path}",
            "parse_confidence": None,
            "entries": [],
        }
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    entries = parse_config_db_trace_log(text)
    return {
        "status": "CAPTURED",
        "source": {"kind": "sim_log_uvm_config_db_trace", "path": str(log_path)},
        "reason": None,
        "parse_confidence": "envelope_verified_message_opaque",
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# env_topology.testplan_correspondence -- the testlist / vPlan /
# coverage-model three-way join (2026-09-04).
#
# THE GAP THIS CLOSES. The spec's Env layer asks for testlist/vPlan/
# coverage-model correspondence. A 2026-09-04 re-audit found `grep -ni
# "testlist\|vplan\|coverage" dv_harness/env_manifest.py` returning zero
# hits, `env_topology` carrying exactly two sub-keys, and the only repo-wide
# "testlist" hits near this theme being `testlist_hash` in prompts.py -- a
# regression run-IDENTITY field, an unrelated concept. Genuinely absent.
#
# WHY THE JOIN IS THE DELIVERABLE. Each of the three lists already exists in
# a real project and each, read alone, always looks healthy: the testlist
# runs, the vPlan has rows, the covergroups compile. Only the join exposes
# the three failures that actually escape --
#   * a vPlan item claiming coverage from a test no regression runs,
#   * a vPlan item measured by a covergroup nobody wrote,
#   * a test burning simulation time against no stated verification intent
#     (and the coverage mirror of it).
# None of these is visible from any single artifact, which is exactly why
# this belongs in the manifest that holds all three.
#
# MATCHING IS A LITERAL NAME JOIN, never fuzzy. A fuzzy matcher would
# manufacture links that do not exist, and the entire value of this layer is
# that its `*_missing` and `orphans` lists can be trusted.
#
# WHAT IS NOT CLAIMED. A vPlan item whose claims all resolve reports LINKED,
# which means "every name this item cites is real" -- it does NOT mean the
# test actually exercises the item or that the covergroup is hitting bins.
# That is a coverage-RESULT question, answered by real coverage data
# (dv_harness/coverage_analysis.py), not by this structural correspondence.
# ---------------------------------------------------------------------------

def load_testplan_sources(path) -> dict:
    """Load and validate a testplan-sources input file against
    testplan_sources.schema.json. Raises TestplanSourcesValidationError."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_testplan_sources(doc)
    return doc


def build_testplan_correspondence(testplan_sources_path=None) -> dict:
    if testplan_sources_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "testplan_sources_json", "path": None},
            "reason": "no testplan-sources input file supplied -- see "
                      "dv_harness/schemas/testplan_sources.schema.json for the expected input contract "
                      "(the project's own real testlist, vPlan items and coverage model exported to one "
                      "shape; never harness-invented tests or coverage)",
            "axes_available": {"testlist": False, "vplan_items": False, "coverage_model": False},
            "items": [],
            "orphans": {"tests_not_in_any_vplan_item": [],
                        "coverage_not_referenced_by_any_vplan_item": []},
            "summary": {"testlist_count": 0, "vplan_item_count": 0, "coverage_model_count": 0,
                        "linked_count": 0, "broken_count": 0, "unclaimed_count": 0,
                        "orphan_test_count": 0, "orphan_coverage_count": 0},
        }
    doc = load_testplan_sources(testplan_sources_path)
    source = {"kind": "testplan_sources_json", "path": str(testplan_sources_path)}
    has_tests = "testlist" in doc
    has_vplan = "vplan_items" in doc
    has_cov = "coverage_model" in doc
    axes = {"testlist": has_tests, "vplan_items": has_vplan, "coverage_model": has_cov}

    if not (has_tests or has_vplan or has_cov):
        return {
            "status": "NOT_AVAILABLE",
            "source": source,
            "reason": f"supplied testplan-sources file carries none of 'testlist', 'vplan_items', "
                      f"'coverage_model': {testplan_sources_path}",
            "axes_available": axes,
            "items": [],
            "orphans": {"tests_not_in_any_vplan_item": [],
                        "coverage_not_referenced_by_any_vplan_item": []},
            "summary": {"testlist_count": 0, "vplan_item_count": 0, "coverage_model_count": 0,
                        "linked_count": 0, "broken_count": 0, "unclaimed_count": 0,
                        "orphan_test_count": 0, "orphan_coverage_count": 0},
        }

    testlist = doc.get("testlist") or []
    vplan_items = doc.get("vplan_items") or []
    coverage_model = doc.get("coverage_model") or []
    test_names = {t["name"] for t in testlist}
    coverage_names = {c["name"] for c in coverage_model}

    items = []
    linked = broken = unclaimed = 0
    claimed_tests = set()
    claimed_coverage = set()
    for vi in vplan_items:
        tests = list(vi.get("tests") or [])
        coverage = list(vi.get("coverage") or [])
        claimed_tests.update(tests)
        claimed_coverage.update(coverage)

        tests_present = sorted(t for t in tests if t in test_names) if has_tests else []
        tests_missing = sorted(t for t in tests if t not in test_names) if has_tests else []
        cov_present = sorted(c for c in coverage if c in coverage_names) if has_cov else []
        cov_missing = sorted(c for c in coverage if c not in coverage_names) if has_cov else []

        # An item is only judged against axes that were actually supplied.
        # Reporting LINKED for claims nothing could check would be the exact
        # false reassurance this layer exists to prevent.
        needs_tests = bool(tests)
        needs_cov = bool(coverage)
        if (needs_tests and not has_tests) or (needs_cov and not has_cov):
            verdict = "NOT_CHECKED"
        elif not needs_tests and not needs_cov:
            verdict = "UNCLAIMED"
            unclaimed += 1
        elif tests_missing and cov_missing:
            verdict = "BROKEN_TEST_AND_COVERAGE_REF"
            broken += 1
        elif tests_missing:
            verdict = "BROKEN_TEST_REF"
            broken += 1
        elif cov_missing:
            verdict = "BROKEN_COVERAGE_REF"
            broken += 1
        else:
            verdict = "LINKED"
            linked += 1

        items.append({
            "id": vi["id"],
            "tests_claimed": len(tests),
            "tests_present": tests_present,
            "tests_missing": tests_missing,
            "coverage_claimed": len(coverage),
            "coverage_present": cov_present,
            "coverage_missing": cov_missing,
            "verdict": verdict,
        })
    items.sort(key=lambda i: i["id"])

    # The reverse direction. Only computable where BOTH sides of a given
    # orphan question were supplied -- an empty list must never be able to
    # mean "we could not look".
    orphan_tests = sorted(n for n in test_names if n not in claimed_tests) if (has_tests and has_vplan) else []
    orphan_cov = sorted(n for n in coverage_names if n not in claimed_coverage) if (has_cov and has_vplan) else []

    status = "COMPUTED" if (has_tests and has_vplan and has_cov) else "PARTIAL"
    reason = None
    if status == "PARTIAL":
        missing_axes = [k for k, v in axes.items() if not v]
        reason = ("correspondence computed over the axes that were supplied; these were not and their "
                  "checks were skipped rather than scored as passing: " + ", ".join(missing_axes))
    return {
        "status": status,
        "source": source,
        "reason": reason,
        "axes_available": axes,
        "items": items,
        "orphans": {
            "tests_not_in_any_vplan_item": orphan_tests,
            "coverage_not_referenced_by_any_vplan_item": orphan_cov,
        },
        "summary": {
            "testlist_count": len(testlist),
            "vplan_item_count": len(vplan_items),
            "coverage_model_count": len(coverage_model),
            "linked_count": linked,
            "broken_count": broken,
            "unclaimed_count": unclaimed,
            "orphan_test_count": len(orphan_tests),
            "orphan_coverage_count": len(orphan_cov),
        },
    }


def build_env_topology(hierarchy_dump_path=None, config_db_trace_log_path=None,
                        testplan_sources_path=None) -> dict:
    return {
        "component_hierarchy": build_component_hierarchy(hierarchy_dump_path),
        "config_db_trace": build_config_db_trace(config_db_trace_log_path),
        "testplan_correspondence": build_testplan_correspondence(testplan_sources_path),
    }


# ---------------------------------------------------------------------------
# top-level assembly
# ---------------------------------------------------------------------------

def generate_env_manifest(*, rtl_files=None, register_map_path=None,
                           vip_config_dump_path=None,
                           topology_dump_path=None, config_db_trace_log_path=None,
                           verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
                           designware_home=None, user_guide_reference_paths=None,
                           soc_arch_map_path=None, testplan_sources_path=None) -> dict:
    """Builds a complete, schema-valid env.manifest.json dict from whatever
    real inputs are supplied. Every parameter is optional -- omitting one
    reports that layer (or sub-layer) as NOT_AVAILABLE with an honest
    reason rather than failing generation outright, since a partial
    manifest (e.g. dut_facts populated, vip_config/env_topology not yet
    captured because no simv has run) is itself a real, useful, honest
    artifact at an early project stage.

    `designware_home` is the one parameter whose omission does NOT mean "not
    available": it falls back to the real $DESIGNWARE_HOME environment
    variable, because the install tree this run would actually compile
    against is a fact about the environment, not a choice the caller makes.
    Pass an explicit path to scan a different install."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.env_manifest", "version": SCHEMA_VERSION},
        "vip_config": build_vip_config_layer(
            vip_config_dump_path,
            designware_home=designware_home,
            user_guide_reference_paths=user_guide_reference_paths,
        ),
        "dut_facts": build_dut_facts(rtl_files, register_map_path, verible_bin=verible_bin,
                                      soc_arch_map_path=soc_arch_map_path),
        "env_topology": build_env_topology(topology_dump_path, config_db_trace_log_path,
                                            testplan_sources_path=testplan_sources_path),
    }
    validate_env_manifest(manifest)
    # Structural, not stylistic: the schema can police the SHAPE of
    # user_guide_refs but cannot notice document prose parked inside a field
    # that is legitimately a string. Runs on every generation, so "never
    # loaded into runtime context" is a property this file is held to rather
    # than a claim its docstring makes.
    assert_no_user_guide_body_in_manifest(manifest)
    return manifest


def generate_and_write(out_path, *, rtl_files=None, register_map_path=None,
                        vip_config_dump_path=None,
                        topology_dump_path=None, config_db_trace_log_path=None,
                        verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
                        designware_home=None, user_guide_reference_paths=None,
                        soc_arch_map_path=None, testplan_sources_path=None) -> dict:
    manifest = generate_env_manifest(
        rtl_files=rtl_files, register_map_path=register_map_path,
        vip_config_dump_path=vip_config_dump_path,
        topology_dump_path=topology_dump_path,
        config_db_trace_log_path=config_db_trace_log_path,
        verible_bin=verible_bin,
        designware_home=designware_home,
        user_guide_reference_paths=user_guide_reference_paths,
        soc_arch_map_path=soc_arch_map_path,
        testplan_sources_path=testplan_sources_path,
    )
    save_env_manifest(manifest, out_path)
    return manifest


# ---------------------------------------------------------------------------
# verible parse -> evidence_db.rtl_modules bridge (2026-09-04)
# ---------------------------------------------------------------------------
#
# THE GAP THIS CLOSES. `evidence_db.insert_rtl_parse()` and its four
# traceability tables (rtl_modules/rtl_ports/rtl_signals/rtl_parameters)
# were real and tested against real verible-derived JSON, and
# `verible_parser.run_export_json()`/`parse_file()` really shell out to
# `verible-verilog-syntax --export_json --printtree` -- but NO code path
# anywhere called both together outside test bodies (both
# .work/evidence-db-wiring-step1-report.md and step2-report.md list
# insert_rtl_parse as "remains unwired"). The one real production caller of
# verible is `dv-harness env-manifest generate`, which routed the parse into
# env.manifest.json and nowhere else. The architecture diagram draws
# `verible JSON/parsers -> DuckDB`; that edge did not exist in code. This
# function is that edge.
#
# It re-uses the parse this generation run ALREADY performed -- it reads
# `manifest["dut_facts"]["rtl"]["files"]`, which is verbatim
# `verible_parser.to_dict(parse_file(...))` per file (see
# build_dut_facts_rtl above), the exact dict shape insert_rtl_parse()
# documents as its input. verible is never re-run, and RTL is never
# re-parsed here.

def ingest_rtl_parse_to_evidence_db(root, manifest: dict) -> list:
    """Land this manifest's real verible parse results as
    `rtl_modules`/`rtl_ports`/`rtl_signals`/`rtl_parameters` rows in the
    project's DuckDB evidence store. Returns the flat list of inserted
    module row ids (empty when nothing was written).

    Writes nothing, and reports it honestly as `[]`, when dut_facts.rtl is
    NOT_AVAILABLE (no --rtl-file was supplied to this generation run) --
    "no RTL was parsed" and "RTL was parsed and had no modules" both
    correctly produce no rows, and neither is ever faked into one.

    RE-GENERATION IS NOT RE-INSERTION. `insert_rtl_parse()` is deliberately
    append-only (a `rtl_modules_id_seq` id plus `parsed_at`, so the store
    keeps the history of a file as it really changed over time), and
    `env-manifest generate` is a command an engineer re-runs routinely,
    often against untouched RTL. Left alone, that combination would grow
    duplicate module/port/signal/parameter rows on every regeneration and
    silently corrupt any "how many modules does this file have" query. So
    this bridge skips a file whose exact
    (file_path, source_sha256, verible_version) parse identity is already
    stored -- identical bytes parsed by the identical tool cannot yield a
    different result, so re-storing it adds no fact. Edit the RTL (new
    source_sha256) or upgrade verible (new verible_version) and the next
    generate really does append a new, genuinely different parse, which is
    the history the append-only design exists to keep. The dedup lives here
    rather than inside `insert_rtl_parse()` because that method's
    append-only contract is already relied on and tested elsewhere; this
    only decides whether THIS caller has anything new to hand it.

    Best-effort, same discipline as every other evidence-store write in
    this project (regression_reporter._write_reconciliation_evidence_if_
    configured, dashboard._ingest_coverage_summary_to_evidence_db,
    fsdb_report.ingest_report_to_evidence_db): a duckdb-not-installed /
    locked-file / disabled-store condition prints and returns [], and must
    never break the env.manifest.json this run already validated and wrote.
    """
    try:
        from . import config as _config
        if not _config.load_config(Path(root)).get("evidence_db", {}).get("enabled", True):
            return []
        rtl = ((manifest or {}).get("dut_facts") or {}).get("rtl") or {}
        files = rtl.get("files") or []
        if not files:
            return []
        from . import evidence_db as _evidence_db
        module_ids = []
        with _evidence_db.EvidenceStore(_evidence_db.default_db_path(Path(root))) as store:
            for parse_result in files:
                already = store.query(
                    "SELECT count(*) FROM rtl_modules WHERE file_path = ? "
                    "AND source_sha256 = ? AND verible_version IS NOT DISTINCT FROM ?",
                    [parse_result.get("file_path"), parse_result.get("source_sha256"),
                     parse_result.get("verible_version")],
                )[0][0]
                if already:
                    continue
                module_ids.extend(store.insert_rtl_parse(parse_result))
        return module_ids
    except Exception as e:
        print(f"[env-manifest] rtl parse evidence store write failed: {e}", flush=True)
        return []


# ---------------------------------------------------------------------------
# env.manifest.json -> Blackboard bridge (2026-09-04)
# ---------------------------------------------------------------------------
#
# THE GAP THIS CLOSES. CLAUDE.md's Blackboard rule says the Blackboard is
# where "current verification truth" lives so any later stage can read it
# through its node's `blackboard_read` declaration (engine.py's
# `_gather_stage_context` snapshots exactly those topics into the real
# prompt). env.manifest.json IS current verification truth -- the captured
# vip_config / dut_facts / env_topology of the environment as it actually
# is -- but it was written ONLY to its own git-tracked fact file: a
# 2026-09-04 audit found zero occurrences of "blackboard" anywhere in this
# module, and no `env_manifest`-shaped topic in any node of
# `.dv-harness/graph/main_graph.json`. A stage that wanted the real VIP
# instance list or the real parsed RTL module names had no blackboard path
# to it at all. This function is that edge.
#
# WHY A SUMMARY AND NOT THE MANIFEST VERBATIM. The blackboard snapshot of a
# node's `blackboard_read` topics is serialized straight into the stage
# prompt (engine.py `_build_plan_section`). `dut_facts.rtl.files` holds the
# full per-file verible parse (every port, signal and parameter of every
# module); pasting that into every reading stage's prompt would drown the
# actual instruction. So this records the layer STATUS/reason/source path
# verbatim -- the honesty contract each builder above establishes, including
# every NOT_AVAILABLE and its real reason -- plus identifying names and
# counts, and points at the manifest file for the full detail. Nothing is
# invented: every field is copied or counted from the real manifest, and a
# NOT_AVAILABLE layer stays NOT_AVAILABLE here rather than being flattened
# into a silent empty list that reads like "captured, and there was nothing".

BLACKBOARD_TOPIC = "env_manifest"


def summarize_for_blackboard(manifest: dict, *, manifest_path=None) -> dict:
    """The blackboard-topic value for one real env.manifest.json dict.

    Prompt-sized by construction (names and counts, never parse trees), and
    honest by construction (each layer's own `status`/`reason` survives
    verbatim, so a reader can always tell "not captured yet" from "captured
    and empty")."""
    manifest = manifest or {}
    vip = manifest.get("vip_config") or {}
    dut = manifest.get("dut_facts") or {}
    rtl = dut.get("rtl") or {}
    regs = dut.get("registers") or {}
    topo = manifest.get("env_topology") or {}
    hier = topo.get("component_hierarchy") or {}
    trace = topo.get("config_db_trace") or {}

    release = vip.get("vip_release") or {}
    guides = vip.get("user_guide_refs") or {}
    addr = dut.get("address_map") or {}
    ckrst = dut.get("clock_reset") or {}
    testplan = topo.get("testplan_correspondence") or {}

    rtl_files = rtl.get("files") or []
    return {
        "manifest_path": str(manifest_path) if manifest_path is not None else None,
        "schema_version": manifest.get("schema_version"),
        "vip_config": {
            "status": vip.get("status"),
            "reason": vip.get("reason"),
            "source": vip.get("source"),
            "instance_count": len(vip.get("vip_instances") or []),
            "instances": [
                {"instance_path": i.get("instance_path"), "vip_type": i.get("vip_type"),
                 "config_field_count": len(i.get("config_fields") or [])}
                for i in (vip.get("vip_instances") or [])
            ],
            # Which VIP release the environment is really built against --
            # name+version only. The release-notes/feature-matrix POINTERS
            # stay in the manifest; a stage that needs one reads it there.
            "vip_release": {
                "status": release.get("status"),
                "reason": release.get("reason"),
                "designware_home": release.get("designware_home"),
                "packages": [
                    {"name": p.get("name"), "version": p.get("version")}
                    for p in (release.get("packages") or [])
                ],
            },
            # Titles and section counts only. Inlining even the section
            # index would defeat the offline-distillation contract this
            # sub-layer exists to keep.
            "user_guide_refs": {
                "status": guides.get("status"),
                "reason": guides.get("reason"),
                "document_count": len(guides.get("documents") or []),
                "documents": [
                    {"title": d.get("title"), "doc_kind": d.get("doc_kind"),
                     "distilled_reference_path": (d.get("distilled_reference") or {}).get("path"),
                     "section_count": d.get("section_count")}
                    for d in (guides.get("documents") or [])
                ],
            },
        },
        "dut_facts": {
            "rtl": {
                "status": rtl.get("status"),
                "reason": rtl.get("reason"),
                "file_count": len(rtl_files),
                "files": [
                    {"file_path": f.get("file_path"), "source_sha256": f.get("source_sha256"),
                     "modules": [m.get("name") for m in (f.get("modules") or [])]}
                    for f in rtl_files
                ],
            },
            "registers": {
                "status": regs.get("status"),
                "reason": regs.get("reason"),
                "source": regs.get("source"),
                "block_count": len(regs.get("blocks") or []),
                "blocks": [b.get("name") for b in (regs.get("blocks") or [])],
            },
            # disagreement_count is carried into the prompt deliberately: a
            # register map and an address map disagreeing about a base is
            # exactly the kind of current-truth conflict a reading stage
            # must not have to open a file to discover.
            "address_map": {
                "status": addr.get("status"),
                "reason": addr.get("reason"),
                "source": addr.get("source"),
                "entry_count": len(addr.get("entries") or []),
                "disagreement_count": addr.get("disagreement_count"),
                "disagreeing_regions": [
                    e.get("name") for e in (addr.get("entries") or [])
                    if e.get("register_map_agreement") == "DISAGREES"
                ],
            },
            "clock_reset": {
                "status": ckrst.get("status"),
                "reason": ckrst.get("reason"),
                "source": ckrst.get("source"),
                "clocks": [c.get("name") for c in (ckrst.get("clocks") or [])],
                "resets": [
                    {"name": r.get("name"), "active_level": r.get("active_level"),
                     "clock_resolved": r.get("clock_resolved")}
                    for r in (ckrst.get("resets") or [])
                ],
            },
        },
        "env_topology": {
            "component_hierarchy": {
                "status": hier.get("status"),
                "reason": hier.get("reason"),
                "source": hier.get("source"),
                "component_count": len(hier.get("components") or []),
            },
            "config_db_trace": {
                "status": trace.get("status"),
                "reason": trace.get("reason"),
                "source": trace.get("source"),
                "parse_confidence": trace.get("parse_confidence"),
                "entry_count": len(trace.get("entries") or []),
            },
            # The summary counts plus the IDs of items whose claims resolve
            # to nothing. A stage planning or signing off work needs the
            # broken links themselves, not just how many there were --
            # the full per-item detail stays in the manifest.
            "testplan_correspondence": {
                "status": testplan.get("status"),
                "reason": testplan.get("reason"),
                "source": testplan.get("source"),
                "axes_available": testplan.get("axes_available"),
                "summary": testplan.get("summary"),
                "broken_item_ids": [
                    i.get("id") for i in (testplan.get("items") or [])
                    if str(i.get("verdict", "")).startswith("BROKEN")
                ],
                "unclaimed_item_ids": [
                    i.get("id") for i in (testplan.get("items") or [])
                    if i.get("verdict") == "UNCLAIMED"
                ],
            },
        },
    }


def sync_to_blackboard(blackboard, manifest: dict, *, manifest_path=None,
                        source: str = "env-manifest") -> dict:
    """Mirror this generation run's real manifest into the Blackboard's
    `env_manifest` topic and return the written entry.

    Called from the ONE real production caller of `generate_and_write()` --
    `dv-harness env-manifest generate` (cli.py) -- so a re-generation always
    refreshes the topic rather than leaving a stale snapshot of an older
    environment behind. `source` lands in the entry's own `source` field, so
    an audit can tell a manifest-sourced topic apart from a stage-sourced
    one at a glance (blackboard.py's entry shape)."""
    return blackboard.write(
        BLACKBOARD_TOPIC,
        summarize_for_blackboard(manifest, manifest_path=manifest_path),
        source=source,
    )
