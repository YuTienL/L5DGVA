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

GENERATION PROVENANCE (schema 1.2, 2026-09-06 -- spec section 210's
per-artifact provenance tuple). `generator` used to carry two fields, and
one of them was a conflation: `version` is env_manifest.py's SCHEMA_VERSION,
so "which harness produced this" had no answer at all, "which agent/skill
produced this" had no field, "which input drove the generation" had no
field, and no git SHA appeared anywhere in the schema. The same `generator`
block now carries all four -- `tool_version` (the real dv_harness package
version, distinct from the schema version it used to be read as), `agent`,
`input_ir` and `repository_sha` -- rather than a second, parallel
provenance record beside it.

The git SHA is read by the EXISTING `change_impact.resolve_sha()` (a real
`git rev-parse --verify HEAD^{commit}`), the same reader
`benchmark_dataset.py` already uses to stamp `harness_git_sha` on an
experiment record; there is no second git reader in this package.

This narrows the diffability contract above, deliberately and honestly: a
manifest regenerated after the HARNESS ITSELF moved to a new commit now
differs in `generator.repository_sha.harness`. That is not clock noise --
the generator that produced the artifact really is a different generator,
which is exactly the fact section 210 exists to record. Unchanged inputs
AND an unchanged harness commit still produce a byte-identical file.

Nothing here is ever fabricated, the same discipline every layer above
follows: an undeclared agent is NOT_DECLARED, a declared identifier that
matches no real `.claude/agents/*.md` or `.claude/skills/**/SKILL.md`
profile in this checkout is recorded DECLARED with resolution NOT_FOUND
(recorded, never accepted as verified), an undeclared input is
NOT_DECLARED, and a git SHA that does not resolve is NOT_AVAILABLE with
the real reason. Provenance never fails generation by default;
`assert_generation_provenance_complete()` (CLI `--require-provenance`) is
the opt-in strict contract, following the same disclosed-default shape as
bind_mechanism_generator's `require_tier`/`require_phy_boundary`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import verible_parser

SCHEMA_VERSION = "1.2"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "env_manifest.schema.json"

#: The repository whose HEAD identifies the GENERATOR that produced a
#: manifest: the checkout containing this file. Resolved from __file__ so a
#: deployed copy under /home/svcacct/AI/Agent stamps its own SHA, not the
#: SHA of whatever project root the caller happened to pass.
HARNESS_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
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


class GenerationProvenanceIncompleteError(ValueError):
    """A manifest's section-210 provenance tuple is not fully answered and the
    caller asked for the strict contract (`--require-provenance`). Raised
    rather than returning False so a strict caller cannot accidentally ship an
    artifact nobody can trace back to an agent, an input and a commit.

    Deliberately NOT raised by default: an undeclared agent is a recorded
    NOT_DECLARED, never a generation failure, so a project that has not adopted
    provenance is never retroactively broken -- the same disclosed-default
    shape as bind_mechanism_generator's require_tier/require_phy_boundary."""


class InputIrDeclarationError(ValueError):
    """The caller declared an input-IR reference this module cannot act on --
    a requirement id with no requirements document (or the reverse), or both
    the requirement-contract form and the plain-file form at once. A caller
    usage error, raised loudly rather than silently recording NOT_DECLARED,
    which would report "nobody declared an input" for a caller who did."""


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
# generation provenance -- spec section 210's per-artifact provenance tuple
# ---------------------------------------------------------------------------
#
# Four questions, answered in the EXISTING `generator` block rather than in a
# second provenance record beside it:
#
#   schema_version  -- already present (top level), unchanged.
#   tool_version    -- NEW. `generator.version` is env_manifest.py's own
#                      SCHEMA_VERSION and was the only version-shaped field,
#                      so "which harness build produced this" was answerable
#                      only by misreading the schema version as one. The real
#                      dv_harness package version now has its own field.
#   agent           -- NEW. Which agent/skill produced the artifact, in the
#                      convention the profiles themselves use to
#                      self-identify: the YAML front-matter `name:` of a
#                      .claude/agents/*.md profile or a .claude/skills/**/
#                      SKILL.md skill. A declared identifier is CHECKED
#                      against the real profiles on disk -- an identifier that
#                      matches none is recorded, never accepted as verified.
#   input_ir        -- NEW. What drove the generation: a SPEC-3 requirement
#                      contract (requirement_id, cross-checked against the
#                      real requirements document through
#                      requirement_contract.validate_requirement_contract() /
#                      downstream_consumable(), so a manifest cannot cite a
#                      requirement that is not actually consumable), or a
#                      plain input file recorded as path + real sha256.
#   repository_sha  -- NEW. The real current git SHA, read by the EXISTING
#                      change_impact.resolve_sha().

#: Where a profile declares its own identity. Both files carry YAML front
#: matter whose `name:` is the identifier every roster/dispatch site already
#: uses (e.g. `.claude/agents/debug-agent.md` -> "debug-agent").
_PROFILE_FRONT_MATTER_FENCE = "---"


def _front_matter_name(path: Path) -> Optional[str]:
    """The `name:` declared in a profile's own YAML front matter, or None.

    A deliberately narrow line scan rather than a YAML dependency: only the
    front-matter block is read, and only its `name:` key, so a profile whose
    body happens to contain a `name:` line cannot contribute an identifier."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != _PROFILE_FRONT_MATTER_FENCE:
        return None
    for line in lines[1:]:
        if line.strip() == _PROFILE_FRONT_MATTER_FENCE:
            return None
        if line.startswith("name:"):
            value = line[len("name:"):].strip().strip("\"'")
            return value or None
    return None


def known_generation_identifiers(profile_root=None) -> Optional[dict]:
    """Every identifier an agent or skill in this checkout may honestly claim.

    Returns {"agents": [...], "skills": [...]} (both sorted) read from the real
    `.claude/agents/*.md` and `.claude/skills/**/SKILL.md` profiles, or None
    when there is no `.claude` tree to check against -- "we could not check"
    stays distinct from "we checked and it is not there", because a deployed
    harness copy without the profile tree must not report every real agent as
    fabricated."""
    root = Path(profile_root) if profile_root is not None else HARNESS_REPOSITORY_ROOT
    claude = root / ".claude"
    if not claude.is_dir():
        return None
    agents, skills = set(), set()
    agents_dir = claude / "agents"
    if agents_dir.is_dir():
        for p in sorted(agents_dir.glob("*.md")):
            name = _front_matter_name(p)
            if name:
                agents.add(name)
    skills_dir = claude / "skills"
    if skills_dir.is_dir():
        for p in sorted(skills_dir.glob("**/SKILL.md")):
            name = _front_matter_name(p)
            if name:
                skills.add(name)
    return {"agents": sorted(agents), "skills": sorted(skills)}


def build_generation_agent(generated_by=None, *, profile_root=None) -> dict:
    """Which agent/skill produced this artifact, and whether that identifier
    resolves to a real profile.

    `resolution` is the honesty axis and has four values that must never
    collapse into each other: AGENT_PROFILE / SKILL (a real profile really
    declares this name), NOT_FOUND (a name was declared and no profile
    carries it -- recorded as declared, never accepted as verified),
    PROFILE_TREE_NOT_AVAILABLE (nobody could check), NOT_DECLARED (nobody
    claimed authorship)."""
    if generated_by is None or not str(generated_by).strip():
        return {
            "status": "NOT_DECLARED",
            "identifier": None,
            "resolution": "NOT_DECLARED",
            "reason": ("no generating agent/skill was declared by the caller; pass "
                       "--generated-by <profile name> (the `name:` of a .claude/agents/*.md "
                       "or .claude/skills/**/SKILL.md profile)"),
        }
    identifier = str(generated_by).strip()
    known = known_generation_identifiers(profile_root)
    if known is None:
        return {
            "status": "DECLARED",
            "identifier": identifier,
            "resolution": "PROFILE_TREE_NOT_AVAILABLE",
            "reason": ("no .claude profile tree is present beside this harness, so the declared "
                       "identifier could not be checked against a real profile"),
        }
    if identifier in known["agents"]:
        return {"status": "DECLARED", "identifier": identifier,
                "resolution": "AGENT_PROFILE", "reason": None}
    if identifier in known["skills"]:
        return {"status": "DECLARED", "identifier": identifier,
                "resolution": "SKILL", "reason": None}
    return {
        "status": "DECLARED",
        "identifier": identifier,
        "resolution": "NOT_FOUND",
        "reason": (f"declared identifier {identifier!r} matches no .claude/agents/*.md and no "
                   ".claude/skills/**/SKILL.md profile in this checkout; recorded as declared, "
                   "never accepted as verified"),
    }


def _repository_sha(root, described_as: str) -> dict:
    """One repository's real HEAD, through change_impact.resolve_sha() -- the
    same `git rev-parse --verify HEAD^{commit}` benchmark_dataset.py already
    stamps an experiment record with. There is no second git reader here."""
    from .change_impact import resolve_sha
    try:
        sha = resolve_sha(Path(root), "HEAD")
    except Exception as exc:  # pragma: no cover - resolve_sha already swallows its own
        return {"status": "NOT_AVAILABLE", "sha": None,
                "reason": f"git HEAD could not be read for {described_as}: {exc}"}
    if sha:
        return {"status": "RESOLVED", "sha": sha, "reason": None}
    return {"status": "NOT_AVAILABLE", "sha": None,
            "reason": (f"git HEAD does not resolve for {described_as} (no git repository, no "
                       "commits yet, or git unavailable)")}


def build_repository_sha(*, project_root=None) -> dict:
    """The two repositories whose commit identifies this artifact.

    `harness` is always attempted -- it identifies the GENERATOR, and is read
    from the checkout containing this file rather than from any caller-supplied
    path, so it cannot be pointed at a different repository. `project` is
    NOT_DECLARED unless the caller names the project root this manifest belongs
    to; no absolute path is recorded for either, keeping the manifest diffable
    across machines."""
    return {
        "harness": _repository_sha(HARNESS_REPOSITORY_ROOT,
                                   "the repository containing dv_harness/env_manifest.py"),
        "project": (
            _repository_sha(project_root, "the declared project root")
            if project_root is not None else
            {"status": "NOT_DECLARED", "sha": None,
             "reason": "no project root was declared for this generation run"}
        ),
    }


def _null_file_ref() -> dict:
    return {"path": None, "sha256": None, "bytes": None}


def _empty_input_ir(status: str, reason: str, *, kind=None, reference=None,
                    source=None, contract_schema_version=None,
                    requirement_status=None, downstream_consumable=None) -> dict:
    """One fixed shape for every input_ir outcome. Every key is always
    present, so "this input was not resolvable" and "this key was omitted"
    can never look alike to a consumer."""
    return {
        "status": status,
        "kind": kind,
        "reference": reference,
        "source": source if source is not None else _null_file_ref(),
        "contract_schema_version": contract_schema_version,
        "requirement_status": requirement_status,
        "downstream_consumable": downstream_consumable,
        "reason": reason,
    }


def build_input_ir(*, requirements_path=None, requirement_id=None,
                   input_file_path=None) -> dict:
    """What drove this generation, in one of two declared forms.

    REQUIREMENT CONTRACT (the SPEC-3 form): a `requirement_id` plus the real
    requirements document it lives in. The record is located, validated
    against requirement_contract.schema.json, and run through
    `downstream_consumable()` -- the decision that module exists to make -- so
    a manifest that cites a requirement records whether that requirement was
    actually fit to generate from, rather than merely naming it.

    FILE (the fallback form, for a project with no contract-shaped IR): a real
    path recorded as path + sha256 + byte size, never content.

    Statuses: NOT_DECLARED / RESOLVED / NOT_FOUND / INVALID."""
    contract_form = requirements_path is not None or requirement_id is not None
    if contract_form and input_file_path is not None:
        raise InputIrDeclarationError(
            "declare either the requirement-contract input form (requirements_path + "
            "requirement_id) or the plain-file form (input_file_path), never both")
    if contract_form and (requirements_path is None or requirement_id is None):
        raise InputIrDeclarationError(
            "the requirement-contract input form needs BOTH a requirements document and a "
            "requirement_id; a requirement id with no document cannot be checked, and a "
            "document with no id does not identify the input that drove generation")

    if not contract_form and input_file_path is None:
        return _empty_input_ir(
            "NOT_DECLARED",
            ("no input IR was declared for this generation run; pass either "
             "--input-requirements/--input-requirement-id (a section 184 requirement "
             "contract) or --input-file (a real driving input file)"))

    if input_file_path is not None:
        p = Path(input_file_path)
        if not p.is_file():
            return _empty_input_ir(
                "NOT_FOUND", f"declared input file does not exist: {p}",
                kind="file", reference=str(p),
                source={"path": str(p), "sha256": None, "bytes": None})
        return _empty_input_ir(
            "RESOLVED", None, kind="file", reference=str(p), source=_file_ref(p))

    doc_path = Path(requirements_path)
    ref = str(requirement_id)
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _empty_input_ir(
            "NOT_FOUND", f"declared requirements document could not be read: {exc}",
            kind="requirement_contract", reference=ref,
            source={"path": str(doc_path), "sha256": None, "bytes": None})

    from . import requirement_contract as _rc
    records = doc.get("requirements", []) if isinstance(doc, dict) else doc
    match = None
    for record in records if isinstance(records, list) else []:
        if _rc.declares_contract_shape(record) and str(record.get("requirement_id")) == ref:
            match = record
            break
    source = _file_ref(doc_path)
    if match is None:
        return _empty_input_ir(
            "NOT_FOUND",
            (f"{doc_path} contains no contract-shaped record with requirement_id {ref!r} "
             "(a record must declare contract_schema_version to be one)"),
            kind="requirement_contract", reference=ref, source=source)
    try:
        _rc.validate_requirement_contract(match)
    except Exception as exc:
        return _empty_input_ir(
            "INVALID", f"requirement {ref!r} is not a schema-valid requirement contract: {exc}",
            kind="requirement_contract", reference=ref, source=source,
            contract_schema_version=match.get("contract_schema_version"),
            requirement_status=match.get("status"))
    consumable, why = _rc.downstream_consumable(match)
    return _empty_input_ir(
        "RESOLVED", why, kind="requirement_contract", reference=ref, source=source,
        contract_schema_version=match.get("contract_schema_version"),
        requirement_status=match.get("status"),
        downstream_consumable=bool(consumable))


def tool_version() -> str:
    """The real dv_harness package version -- distinct from SCHEMA_VERSION,
    which `generator.version` carries and which was previously the only
    version-shaped field in the block."""
    try:
        from . import __version__ as package_version
    except ImportError:  # pragma: no cover - the package always defines it
        return "UNKNOWN"
    return str(package_version)


def build_generator_block(*, generated_by=None, profile_root=None, project_root=None,
                          requirements_path=None, requirement_id=None,
                          input_file_path=None) -> dict:
    """The `generator` block: the existing tool/version pair plus section
    210's three previously-absent provenance answers."""
    return {
        "tool": "dv_harness.env_manifest",
        "version": SCHEMA_VERSION,
        "tool_version": tool_version(),
        "agent": build_generation_agent(generated_by, profile_root=profile_root),
        "input_ir": build_input_ir(requirements_path=requirements_path,
                                   requirement_id=requirement_id,
                                   input_file_path=input_file_path),
        "repository_sha": build_repository_sha(project_root=project_root),
    }


def generation_provenance(manifest: dict) -> dict:
    """The section-210 tuple, flattened for a consumer that wants to answer
    "who/what/which commit produced this artifact" without walking the block."""
    generator = (manifest or {}).get("generator") or {}
    agent = generator.get("agent") or {}
    input_ir = generator.get("input_ir") or {}
    repo = generator.get("repository_sha") or {}
    harness = repo.get("harness") or {}
    project = repo.get("project") or {}
    return {
        "schema_version": (manifest or {}).get("schema_version"),
        "tool": generator.get("tool"),
        "tool_version": generator.get("tool_version"),
        "agent_identifier": agent.get("identifier"),
        "agent_resolution": agent.get("resolution"),
        "input_ir_kind": input_ir.get("kind"),
        "input_ir_reference": input_ir.get("reference"),
        "input_ir_status": input_ir.get("status"),
        "harness_sha": harness.get("sha"),
        "project_sha": project.get("sha"),
    }


def provenance_gaps(manifest: dict) -> list:
    """Which parts of the provenance tuple this manifest does NOT answer, as
    concrete reasons. Empty means every part is answered by real content."""
    generator = (manifest or {}).get("generator") or {}
    agent = generator.get("agent") or {}
    input_ir = generator.get("input_ir") or {}
    harness = (generator.get("repository_sha") or {}).get("harness") or {}
    gaps = []
    if not (manifest or {}).get("schema_version"):
        gaps.append("schema_version is absent")
    if not generator.get("tool_version"):
        gaps.append("generator.tool_version is absent")
    if agent.get("status") != "DECLARED":
        gaps.append("generator.agent: " + (agent.get("reason") or "no agent declared"))
    elif agent.get("resolution") not in ("AGENT_PROFILE", "SKILL"):
        gaps.append("generator.agent: " + (agent.get("reason") or "declared agent did not resolve"))
    if input_ir.get("status") != "RESOLVED":
        gaps.append("generator.input_ir: " + (input_ir.get("reason") or "no input IR declared"))
    if harness.get("status") != "RESOLVED":
        gaps.append("generator.repository_sha.harness: "
                    + (harness.get("reason") or "harness git SHA not resolved"))
    return gaps


def assert_generation_provenance_complete(manifest: dict) -> None:
    """Strict, opt-in section-210 contract: every part of the tuple is
    answered by real content. Raises GenerationProvenanceIncompleteError
    naming every gap at once, because a caller fixing provenance wants the
    whole list rather than one item per run."""
    gaps = provenance_gaps(manifest)
    if gaps:
        raise GenerationProvenanceIncompleteError(
            "generation provenance is incomplete:\n  - " + "\n  - ".join(gaps))


# ---------------------------------------------------------------------------
# top-level assembly
# ---------------------------------------------------------------------------

def generate_env_manifest(*, rtl_files=None, register_map_path=None,
                           vip_config_dump_path=None,
                           topology_dump_path=None, config_db_trace_log_path=None,
                           verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
                           designware_home=None, user_guide_reference_paths=None,
                           soc_arch_map_path=None, testplan_sources_path=None,
                           generated_by=None, profile_root=None, project_root=None,
                           input_requirements_path=None, input_requirement_id=None,
                           input_file_path=None, require_provenance: bool = False) -> dict:
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
    Pass an explicit path to scan a different install.

    The provenance parameters (`generated_by`, the two input-IR forms,
    `project_root`) follow the same rule: omitting one records an honest
    NOT_DECLARED and never fails generation. `require_provenance=True` is the
    opt-in strict contract and raises GenerationProvenanceIncompleteError."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": build_generator_block(
            generated_by=generated_by, profile_root=profile_root,
            project_root=project_root,
            requirements_path=input_requirements_path,
            requirement_id=input_requirement_id,
            input_file_path=input_file_path,
        ),
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
    if require_provenance:
        assert_generation_provenance_complete(manifest)
    return manifest


def generate_and_write(out_path, *, rtl_files=None, register_map_path=None,
                        vip_config_dump_path=None,
                        topology_dump_path=None, config_db_trace_log_path=None,
                        verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
                        designware_home=None, user_guide_reference_paths=None,
                        soc_arch_map_path=None, testplan_sources_path=None,
                        generated_by=None, profile_root=None, project_root=None,
                        input_requirements_path=None, input_requirement_id=None,
                        input_file_path=None, require_provenance: bool = False) -> dict:
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
        generated_by=generated_by, profile_root=profile_root, project_root=project_root,
        input_requirements_path=input_requirements_path,
        input_requirement_id=input_requirement_id,
        input_file_path=input_file_path,
        require_provenance=require_provenance,
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
        # Section 210's provenance tuple, flattened. A stage reading this
        # topic must be able to tell WHICH agent, WHICH input and WHICH
        # harness commit produced the facts it is about to reason over
        # without opening the manifest file.
        "generation_provenance": generation_provenance(manifest),
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


def default_manifest_path(project_root) -> Optional[Path]:
    """The project's real env.manifest.json path if one exists on disk, else
    None.

    Resolved through `context_budget`'s tier-2 always-resident declaration
    (path + alt_paths) rather than a second hardcoded literal -- that policy
    entry is the one place in this repo that owns the path, and
    `mcp/claude_md_index.manifest_rel_path()` already reads it from there
    for the same reason. This module's own CLI takes `--out` and owns no
    default."""
    from . import context_budget
    try:
        policy = context_budget.load_policy()
    except Exception:
        return None
    for art in policy.get("always_resident", []) or []:
        if str(art.get("path", "")).endswith("env.manifest.json"):
            return context_budget.resolve_artifact(art, Path(project_root))
    return None


def ensure_blackboard_topic(project_root, *, blackboard=None, manifest_path=None) -> dict:
    """Make the `env_manifest` topic PRESENT on the automatic engine path,
    from the manifest already on disk (2026-09-04).

    Why this exists: `sync_to_blackboard()` above is real and fires, but its
    only caller is the interactive `dv-harness env-manifest generate`
    command, and a 2026-09-04 audit confirmed `engine.py` has zero
    references to this module, no graph node prompt instructs an agent to
    run that command, and no CI job runs it. So a fully autonomous
    `engine.loop()` from INTAKE to SIGNOFF could complete with the topic
    permanently absent while ARCH_DISCOVERY / PROJECT_MODEL / IMPLEMENT all
    declare it in `blackboard_read`. The engine now calls this before every
    stage that declares the topic.

    Deliberately a MIRROR of an existing manifest, never a generation. This
    module's generator needs real inputs the engine does not have (RTL file
    list, register map, SoC arch map, testplan sources -- all `--flag`
    arguments of the CLI), and inventing a manifest from nothing would be
    exactly the fabrication the manifest's own honesty contract forbids. A
    project that has never generated one gets `MANIFEST_NOT_GENERATED` plus
    the real command that produces it, which is an honest absence.

    Only fills an ABSENT topic: `dv-harness env-manifest generate` already
    refreshes it on every real regeneration (it is the sole writer of
    env.manifest.json), so re-summarising an unchanged manifest on every
    stage would be write churn with no new truth in it.

    Never raises. A schema-invalid manifest on disk (e.g. a stale 1.0 file
    that `load_env_manifest()` rejects) is reported as MANIFEST_INVALID and
    leaves the topic absent -- it must not take down an unrelated stage,
    and it must not be mirrored as if it were current truth either."""
    root = Path(project_root)
    if blackboard is None:
        from .blackboard import Blackboard
        blackboard = Blackboard(root)
    try:
        if blackboard.read(BLACKBOARD_TOPIC) is not None:
            return {"topic": BLACKBOARD_TOPIC, "action": "ALREADY_PRESENT"}
        path = Path(manifest_path) if manifest_path else default_manifest_path(root)
        if path is None or not Path(path).is_file():
            return {"topic": BLACKBOARD_TOPIC, "action": "MANIFEST_NOT_GENERATED",
                    "produces_it": "dv-harness env-manifest generate --out "
                                   ".dv-harness/env.manifest.json"}
        manifest = load_env_manifest(path)
        sync_to_blackboard(blackboard, manifest, manifest_path=str(path))
        return {"topic": BLACKBOARD_TOPIC, "action": "SYNCED_FROM_MANIFEST",
                "manifest_path": str(path)}
    except Exception as exc:
        return {"topic": BLACKBOARD_TOPIC, "action": "MANIFEST_INVALID",
                "error": f"{type(exc).__name__}: {exc}"}
