"""dv_harness/mcp/verbs.py -- the 5 fixed verbs' real logic, as plain
framework-agnostic JSON-in/JSON-out functions (no dependency on any MCP
transport SDK -- `server.py` is the thin wrapper layered on top of these).

get_vip_config / get_dut_port / get_register / get_topology read from an
already-loaded env.manifest.json dict (see manifest_source.load_manifest())
-- they never open a file themselves. query_regression reads through a
caller-supplied dv_harness.evidence_db.EvidenceStore's own `.query(sql,
params)` method only (see regression_queries.py for the fixed SQL shapes) --
it never calls any of that store's insert_*/write methods.

Field names below match the REAL, now-landed
dv_harness/schemas/env_manifest.schema.json (dv_harness/env_manifest.py) --
`vip_config.vip_instances[].config_fields`, `dut_facts.rtl.files[].modules`,
`dut_facts.registers.blocks[].registers[]`,
`env_topology.component_hierarchy.components`,
`env_topology.config_db_trace.entries`. This is a RECONCILED integration,
not the originally-assumed shape this package was first built against while
the manifest-generator workstream was still running in parallel -- see
.work/mcp-server-report.md for the before/after and
dv_harness_tests/test_mcp_env_manifest_integration.py for a test that builds
a manifest through the real generator itself, not just a hand-authored
fixture.

Every function here validates its `params` against schema.PARAM_SCHEMAS[verb]
before doing anything else, and validates the dict it is about to return
against schema.RESULT_SCHEMAS[verb] before returning it -- so a malformed
call or a malformed result can never silently pass through."""
from __future__ import annotations

from typing import Any, Optional

from . import regression_queries, schema
from .errors import McpUnknownVerbError, McpValidationError


def get_vip_config(manifest: dict, params: dict) -> dict:
    """VIP layer (Part A): a VIP instance's own already-resolved config,
    captured from a zero-time end_of_elaboration_phase dump -- never
    documentation. Reads manifest["vip_config"] (status CAPTURED |
    NOT_AVAILABLE, vip_instances[].{instance_path, vip_type, config_fields}
    -- config_fields is a flat string->string map, exactly as the VIP's own
    config object reported it, never reinterpreted here).
    `params.instance_path`/`params.vip_type` narrow the match; omitting
    both returns every captured instance."""
    schema.validate_params("get_vip_config", params)
    vip = manifest.get("vip_config") or {}
    status = vip.get("status", "NOT_AVAILABLE")
    if status != "CAPTURED":
        result = {
            "verb": "get_vip_config",
            "status": status,
            "reason": vip.get("reason") or "manifest has no vip_config.status == CAPTURED section",
            "instances": [],
        }
        schema.validate_result("get_vip_config", result)
        return result

    instance_path = params.get("instance_path")
    vip_type = params.get("vip_type")
    instances = [
        inst for inst in vip.get("vip_instances", [])
        if (instance_path is None or inst.get("instance_path") == instance_path)
        and (vip_type is None or inst.get("vip_type") == vip_type)
    ]
    result = {"verb": "get_vip_config", "status": "CAPTURED",
               "instances": instances, "match_count": len(instances)}
    schema.validate_result("get_vip_config", result)
    return result


def get_dut_port(manifest: dict, params: dict) -> dict:
    """DUT layer (Part A): ports + parameters for one module, sourced from
    dut_facts.rtl (status PARSED | NOT_AVAILABLE, files[].{file_path,
    source_sha256, verible_version, modules[]} -- verible_parser.to_dict()'s
    own real, unmodified shape, nested one level under each source file it
    came from). `params.module_name` is required; `params.port_name`
    narrows to one port. A module name is searched across EVERY file's
    modules list (a project can legitimately declare more than one module
    per file, or the same module name could -- incorrectly -- appear twice
    across files; the first match wins, same "first match" convention
    verible_parser.extract_modules() itself already uses for a duplicate
    tag within one file)."""
    schema.validate_params("get_dut_port", params)
    module_name = params["module_name"]
    rtl = (manifest.get("dut_facts") or {}).get("rtl") or {}
    if rtl.get("status") != "PARSED":
        result = {
            "verb": "get_dut_port", "status": "NOT_AVAILABLE", "module_name": module_name,
            "reason": rtl.get("reason") or "manifest has no dut_facts.rtl.status == PARSED section",
            "ports": [], "parameters": [],
        }
        schema.validate_result("get_dut_port", result)
        return result

    match = None
    file_entry = None
    for f in rtl.get("files", []):
        mod = next((m for m in f.get("modules", []) if m.get("name") == module_name), None)
        if mod is not None:
            match, file_entry = mod, f
            break

    if match is None:
        result = {
            "verb": "get_dut_port", "status": "NOT_FOUND", "module_name": module_name,
            "reason": f"no module named {module_name!r} in any dut_facts.rtl.files[].modules",
            "ports": [], "parameters": [],
        }
        schema.validate_result("get_dut_port", result)
        return result

    ports = match.get("ports", [])
    port_name = params.get("port_name")
    if port_name is not None:
        ports = [p for p in ports if p.get("name") == port_name]
    result = {
        "verb": "get_dut_port", "status": "FOUND", "module_name": module_name,
        "file_path": file_entry.get("file_path"), "source_sha256": file_entry.get("source_sha256"),
        "ports": ports, "parameters": match.get("parameters", []),
    }
    schema.validate_result("get_dut_port", result)
    return result


def _absolute_address(base_address: str, address_offset: str) -> str:
    """base_address/address_offset are both '0x...'-prefixed hex strings
    per register_map.schema.json; a register's real absolute address is
    their sum. Formatted uppercase to match that schema's own
    `^0x[0-9A-Fa-f]+$` pattern."""
    return f"0x{int(base_address, 16) + int(address_offset, 16):X}"


def get_register(manifest: dict, params: dict) -> dict:
    """DUT layer (Part A): register facts from a structured RAL/IP-XACT-
    style source (dut_facts.registers, status LOADED | NOT_AVAILABLE,
    blocks[].{name, base_address, registers[]} -- register_map.schema.json's
    own block/register/field shape, passed through unmodified) -- never a
    raw Excel/PDF scrape, and never fabricated when that source isn't
    present (status NOT_AVAILABLE, reported honestly).
    `params.block_name`/`params.name` filter by name; `params.address`
    matches EITHER a register's own `address_offset` OR its absolute
    address (block base_address + address_offset, computed here -- see
    `_absolute_address()`), since a caller may reasonably know either
    form. Every returned entry is annotated with its enclosing
    `block_name`/`block_base_address` and computed `absolute_address` so a
    caller never has to re-derive block context itself."""
    schema.validate_params("get_register", params)
    regs = (manifest.get("dut_facts") or {}).get("registers") or {}
    status = regs.get("status", "NOT_AVAILABLE")
    if status != "LOADED":
        result = {
            "verb": "get_register", "status": status,
            "reason": regs.get("reason") or "manifest has no dut_facts.registers.status == LOADED section",
            "registers": [],
        }
        schema.validate_result("get_register", result)
        return result

    block_name = params.get("block_name")
    name = params.get("name")
    address = params.get("address")
    matches = []
    for block in regs.get("blocks", []):
        if block_name is not None and block.get("name") != block_name:
            continue
        base_address = block.get("base_address")
        for reg in block.get("registers", []):
            if name is not None and reg.get("name") != name:
                continue
            absolute_address = _absolute_address(base_address, reg["address_offset"])
            if address is not None and address not in (reg.get("address_offset"), absolute_address):
                continue
            matches.append({
                **reg,
                "block_name": block.get("name"),
                "block_base_address": base_address,
                "absolute_address": absolute_address,
            })

    result = {"verb": "get_register", "status": "LOADED",
               "registers": matches, "match_count": len(matches)}
    schema.validate_result("get_register", result)
    return result


def get_topology(manifest: dict, params: dict) -> dict:
    """Env layer (Part A): component hierarchy + raw config_db SET/GET
    trace from uvm_top.print_topology() + +UVM_CONFIG_DB_TRACE, so "is this
    component active or passive" is answered from real captured evidence
    (env_topology.component_hierarchy.components[].is_active, one of
    UVM_ACTIVE/UVM_PASSIVE/NOT_APPLICABLE), never guessed from naming.

    HONEST LIMITATION on Part C's "a set with no get is direct evidence of
    a miswired vif": the real generator's env_topology.config_db_trace
    entries are ENVELOPE-parsed only (kind/file/line/time/reporter are real,
    structured fields) -- entries[].message, the part of a real UVM
    CFGDB/SET or CFGDB/GET report that would actually name the config_db
    context/field_name, is left OPAQUE, unparsed raw text
    (parse_confidence == "envelope_verified_message_opaque"; see
    dv_harness/env_manifest.py's own parse_config_db_trace_log()). Pairing
    a SET to its corresponding GET therefore requires parsing that message
    body, which has never been verified against a live UVM run in this
    repo -- so THIS verb does not invent a per-field matched/unmatched
    verdict from unparsed text (that would be exactly the kind of guess the
    Evidence Truth Rule forbids). It returns the raw entries (filterable by
    `reporter` prefix via `path_prefix`) plus honest SET/GET event COUNTS
    only. A caller wanting the real per-field miswiring check this task's
    Part C describes needs entries[].message to first gain structured
    field_name/context parsing in the generator itself -- flagged as a real
    open gap in .work/mcp-server-report.md, not silently worked around
    here."""
    schema.validate_params("get_topology", params)
    env = manifest.get("env_topology") or {}
    hierarchy = env.get("component_hierarchy") or {}
    trace = env.get("config_db_trace") or {}
    path_prefix = params.get("path_prefix")
    component_type = params.get("component_type")

    hierarchy_status = hierarchy.get("status", "NOT_AVAILABLE")
    components = []
    if hierarchy_status == "CAPTURED":
        components = [
            c for c in hierarchy.get("components", [])
            if (path_prefix is None or str(c.get("full_name", "")).startswith(path_prefix))
            and (component_type is None or c.get("type_name") == component_type)
        ]

    trace_status = trace.get("status", "NOT_AVAILABLE")
    config_db_entries: list = []
    if trace_status == "CAPTURED" and params.get("include_config_db", True):
        config_db_entries = [
            e for e in trace.get("entries", [])
            if path_prefix is None or str(e.get("reporter", "")).startswith(path_prefix)
        ]

    result = {
        "verb": "get_topology",
        "component_hierarchy_status": hierarchy_status,
        "component_hierarchy_reason": hierarchy.get("reason"),
        "components": components,
        "config_db_trace_status": trace_status,
        "config_db_trace_reason": trace.get("reason"),
        "config_db_trace_parse_confidence": trace.get("parse_confidence"),
        "config_db_entries": config_db_entries,
        "config_db_set_event_count": sum(1 for e in config_db_entries if e.get("kind") == "SET"),
        "config_db_get_event_count": sum(1 for e in config_db_entries if e.get("kind") == "GET"),
    }
    schema.validate_result("get_topology", result)
    return result


def query_regression(evidence_store: Any, params: dict) -> dict:
    """Regression evidence: reads through
    dv_harness.evidence_db.EvidenceStore.query(sql, params) using ONE of a
    fixed set of parameterized query shapes (regression_queries.QUERY_SHAPES)
    -- never caller-supplied raw SQL, which would defeat the entire
    fixed-verb design this system exists to enforce."""
    schema.validate_params("query_regression", params)
    query_shape = params["query_shape"]
    rows = regression_queries.run_query(evidence_store, query_shape, params)
    result = {"verb": "query_regression", "status": "OK",
               "query_shape": query_shape, "row_count": len(rows), "rows": rows}
    schema.validate_result("query_regression", result)
    return result


VERBS = {
    "get_vip_config": get_vip_config,
    "get_dut_port": get_dut_port,
    "get_register": get_register,
    "get_topology": get_topology,
    "query_regression": query_regression,
}


def dispatch(verb: str, params: Optional[dict] = None, *,
              manifest: Optional[dict] = None, evidence_store: Any = None) -> dict:
    """The single fixed dispatch point: `verb` MUST be exactly one of the 5
    names in VERBS -- there is no free-text/catch-all fallback branch. This
    is the auditability property Part A asks for: every possible query this
    server can ever answer is one of these 5 known shapes."""
    if verb not in VERBS:
        raise McpUnknownVerbError(
            f"{verb!r} is not one of the 5 fixed MCP verbs: {sorted(VERBS)}")
    params = params or {}
    if verb == "query_regression":
        if evidence_store is None:
            raise McpValidationError("query_regression requires an evidence_store")
        return query_regression(evidence_store, params)
    if manifest is None:
        raise McpValidationError(f"{verb} requires a loaded env.manifest.json dict")
    return VERBS[verb](manifest, params)
