"""dv_harness/env_manifest.py -- generator for env.manifest.json, a
generated, diffable, git-tracked fact file with exactly three top-level
layers (Part A of the 2026-09-03 env.manifest.json + MCP + question-queue
spec):

  vip_config   -- the VIP's own already-resolved config object, as a real
                  UVM simv would dump it via a zero-time
                  end_of_elaboration_phase callback (see
                  dv_harness/uvm_generator/templates/uvm_env_manifest/
                  dv_env_manifest_pkg.sv for the generic template code a
                  generated environment includes to produce that dump).
  dut_facts    -- ports/params/signals reverse-derived from real verible
                  --export_json RTL parsing (extends
                  dv_harness/verible_parser.py's own parse_file()/to_dict()
                  output -- this module does NOT re-implement RTL parsing),
                  plus registers read from a structured RAL/IP-XACT-style
                  input file (see dv_harness/schemas/register_map.schema.json
                  for that input contract).
  env_topology -- component hierarchy + config_db set/get trace, captured
                  from a real uvm_top run (see the same template package
                  for the hierarchy-dump mechanism; +UVM_CONFIG_DB_TRACE is
                  a native UVM plusarg needing no template code).

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

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "env_manifest.schema.json"
REGISTER_MAP_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "register_map.schema.json"


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


def build_dut_facts(rtl_files=None, register_map_path=None,
                     verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN) -> dict:
    return {
        "rtl": build_dut_facts_rtl(rtl_files, verible_bin=verible_bin),
        "registers": build_dut_facts_registers(register_map_path),
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


def build_env_topology(hierarchy_dump_path=None, config_db_trace_log_path=None) -> dict:
    return {
        "component_hierarchy": build_component_hierarchy(hierarchy_dump_path),
        "config_db_trace": build_config_db_trace(config_db_trace_log_path),
    }


# ---------------------------------------------------------------------------
# top-level assembly
# ---------------------------------------------------------------------------

def generate_env_manifest(*, rtl_files=None, register_map_path=None,
                           vip_config_dump_path=None,
                           topology_dump_path=None, config_db_trace_log_path=None,
                           verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN) -> dict:
    """Builds a complete, schema-valid env.manifest.json dict from whatever
    real inputs are supplied. Every parameter is optional -- omitting one
    reports that layer (or sub-layer) as NOT_AVAILABLE with an honest
    reason rather than failing generation outright, since a partial
    manifest (e.g. dut_facts populated, vip_config/env_topology not yet
    captured because no simv has run) is itself a real, useful, honest
    artifact at an early project stage."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.env_manifest", "version": SCHEMA_VERSION},
        "vip_config": build_vip_config(vip_config_dump_path),
        "dut_facts": build_dut_facts(rtl_files, register_map_path, verible_bin=verible_bin),
        "env_topology": build_env_topology(topology_dump_path, config_db_trace_log_path),
    }
    validate_env_manifest(manifest)
    return manifest


def generate_and_write(out_path, *, rtl_files=None, register_map_path=None,
                        vip_config_dump_path=None,
                        topology_dump_path=None, config_db_trace_log_path=None,
                        verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN) -> dict:
    manifest = generate_env_manifest(
        rtl_files=rtl_files, register_map_path=register_map_path,
        vip_config_dump_path=vip_config_dump_path,
        topology_dump_path=topology_dump_path,
        config_db_trace_log_path=config_db_trace_log_path,
        verible_bin=verible_bin,
    )
    save_env_manifest(manifest, out_path)
    return manifest
