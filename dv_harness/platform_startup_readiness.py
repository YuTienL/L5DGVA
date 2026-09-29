"""dv_harness/platform_startup_readiness.py -- a STARTUP-TIME readiness check:
is the harness itself correctly configured, are its declared dependencies
present, is config.json valid -- distinct from `platform_health.py`, which is
an ONGOING OPERATIONAL health aggregator reading recorded RUN HISTORY
(`degradation.describe()`'s trigger record, the `EXECUTION_PREFLIGHT_PASS`/
`..._BLOCKED` event trail, the last `connectivity_check` gate run,
`regression_verdict_history`). Its own docstring is explicit about what it
reads: "every piece of it lived in a different file... nothing in this file
measures anything itself". This module answers a NARROWER, EARLIER question
none of that machinery can answer yet: before a single stage has ever run --
before there is any recorded history to aggregate -- can this harness even
start.

REUSE OVER REINVENT: `platform_health.SUBSYSTEMS` is the real, already-
established subsystem taxonomy for "what does this harness's own platform
consist of". This module iterates that SAME taxonomy as its starting point
(never re-typing a parallel list -- `assert_reuses_platform_health_taxonomy()`
checks this at import) and, for each subsystem, either derives a genuine
STARTUP-relevant check or honestly reports `NOT_APPLICABLE_AT_STARTUP` naming
why that subsystem needs operational history this harness cannot have before
a first run.

Four of platform_health's eight subsystems ARE checkable at startup, computed
HERE from CONFIGURATION alone -- never by probing a live license server or
scheduler, which needs a Runner/transport this module deliberately never
constructs (see `preflight.py`, the real live-probe mechanism, and
`degradation.py`'s own transport-injection precedent for why "a command is
not on PATH" must never be read as evidence of a jammed farm):
  - agent_adapter          -- is the configured adapter command actually
    resolvable right now (`adapters.cli.ClaudeCLIAdapter._resolve_command()`,
    reused verbatim -- there is no second command-resolution routine here).
  - eda_license / lsf_queue / execution_environment -- folded into one
    `execution_preflight_configuration` check: would
    `preflight.config_from_dict()` (reused, not re-derived) build a
    `PreflightConfig` whose field TYPES are actually usable by that module's
    own real checks at run time. This is a SHAPE check, never a live lmstat/
    bqueues probe -- an unconfigured (empty) `license_server`/`workdir` is a
    normal, expected state for a project that has not yet been pointed at a
    real remote server (see `config.py`'s own comment on those two fields)
    and is never reported as a startup blocker on that basis alone.

The other four (`connectivity_gates`, `regression_quality`,
`harness_self_reporting`, `slo_compliance`) need a completed run's own
recorded evidence and are reported `NOT_APPLICABLE_AT_STARTUP`.

Two subsystems have NO platform_health counterpart at all, because
platform_health's own docstring states it reads mechanisms that ALREADY EXIST
once a project has run at least once -- neither of these has produced any
evidence yet at startup:
  - harness_configuration -- does `.dv-harness/config.json` (if present)
    parse as JSON, and does every top-level block's TYPE actually match
    `config.DEFAULT_CONFIG`'s own shape (a block that fails this would be
    silently OVERWRITTEN rather than merged by `config.load_config()`'s own
    `isinstance(v, dict) and isinstance(merged.get(k), dict)` merge rule --
    see `assess_harness_configuration()`'s own docstring for the concrete
    failure this catches). This module reads the file directly with a plain
    `read_text()`/`json.loads()` and NEVER calls `config.load_config()` --
    that function WRITES a default `config.json` to disk the first time it is
    called for a project that has none, and a read-only startup check must
    never mint the very file it is checking (the same "reading is never a
    mutating act" discipline `golden_flow_readiness.py`/`signoff_export.py`
    already apply to `state.json`).
  - python_dependencies -- are this project's own DECLARED Python
    dependencies (pyproject.toml / requirements*.txt) actually importable for
    the CURRENT interpreter, reusing `dependency_supply_chain.build_inventory()`
    / `check_declared_vs_installed()` rather than a second dependency scanner
    or a second `importlib.metadata` reader.

A ninth, also new: `project_state_directory` -- can `.dv-harness/` actually be
created and written to on this machine. Every persisted artifact this harness
produces (`state.json`, `events.jsonl`, `evidence.duckdb`, ...) depends on
this being true, and nothing upstream of this module checks it before the
first real write attempt.

WORST-WINS, no averaging (this project's own standing rule for a rollup gate):
the overall verdict is the worst subsystem verdict among the subsystems that
actually apply at startup, folded through `golden_flow_readiness.
combine_readiness()` -- REUSED, not re-derived, so this module's fold can
never silently disagree with the fold every other readiness-matrix module in
this codebase already uses. A `NOT_APPLICABLE_AT_STARTUP` subsystem never
counts toward that fold in either direction: it is not evidence of health OR
of a problem, it is a statement that this question cannot be asked yet.

AUTHORIZES NOTHING. Like `platform_health.py`, this module imports no
approval machinery and performs no persisted write of its own -- the one
disk touch (`assess_project_state_directory()`) creates a single throwaway
temp file to prove writability and deletes it in the same call, never a
directory or file this module leaves behind.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import platform_health as _platform_health
from .golden_flow_readiness import combine_readiness
from .subsystem_discovery import READY, PARTIAL, BLOCKED, UNKNOWN

#: This module's own status for a platform_health subsystem id that needs
#: operational run history this harness cannot have before a first run.
#: Deliberately NOT one of subsystem_discovery.READINESS_CLASSES -- folding it
#: into UNKNOWN would present "this question cannot be asked yet" as
#: indistinguishable from "we tried to measure this and could not".
NOT_APPLICABLE_AT_STARTUP = "NOT_APPLICABLE_AT_STARTUP"

# --------------------------------------------------------------------------
# Subsystem ids -- this module's two genuinely new ones, plus a name for the
# one folded startup-relevant check platform_health splits into three
# (eda_license / lsf_queue / execution_environment), plus platform_health's
# own agent_adapter id (computed here from configuration, never from
# recorded degradation history).
# --------------------------------------------------------------------------

SUBSYS_HARNESS_CONFIGURATION = "harness_configuration"
SUBSYS_PYTHON_DEPENDENCIES = "python_dependencies"
SUBSYS_PROJECT_STATE_DIRECTORY = "project_state_directory"
SUBSYS_EXECUTION_PREFLIGHT_CONFIG = "execution_preflight_configuration"

#: platform_health subsystems this module can genuinely check at startup,
#: mapped to the local id this module reports for it. agent_adapter keeps
#: platform_health's own id (same subsystem, a different, startup-specific
#: computation); eda_license/lsf_queue/execution_environment are three
#: distinct operational subsystems in platform_health but collapse to ONE
#: config-shape question here, since none of the three can be told apart
#: without a live probe this module never performs.
_STARTUP_CHECKABLE_PLATFORM_HEALTH_SUBSYSTEMS: Dict[str, str] = {
    _platform_health.SUBSYS_AGENT_ADAPTER: _platform_health.SUBSYS_AGENT_ADAPTER,
    _platform_health.SUBSYS_EDA_LICENSE: SUBSYS_EXECUTION_PREFLIGHT_CONFIG,
    _platform_health.SUBSYS_LSF_QUEUE: SUBSYS_EXECUTION_PREFLIGHT_CONFIG,
    _platform_health.SUBSYS_EXECUTION_ENV: SUBSYS_EXECUTION_PREFLIGHT_CONFIG,
}

#: The remaining four platform_health subsystems, and the real reason each
#: needs operational history this harness cannot have before a first run.
_NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS: Dict[str, str] = {
    _platform_health.SUBSYS_CONNECTIVITY_GATES: (
        "platform_health.assess_connectivity_gates() reads the last recorded "
        "connectivity_check gate run (connectivity_check.load_state()) -- no "
        "gate has run yet at startup, so there is no recorded run to evaluate."),
    _platform_health.SUBSYS_REGRESSION_QUALITY: (
        "platform_health.assess_regression_quality() reads trend_analysis."
        "trend_report() over evidence.duckdb's regression_verdict_history -- "
        "no regression has ever run yet at startup."),
    _platform_health.SUBSYS_SELF_REPORTING: (
        "platform_health.assess_harness_self_reporting() reads a trailing "
        "window of .dv-harness/events.jsonl for *_FAILED side-channel events "
        "-- a project that has never run has no events.jsonl to read."),
    _platform_health.SUBSYS_SLO_COMPLIANCE: (
        "platform_health.assess_slo_compliance() folds the error-budget "
        "verdicts computed from execution-preflight/regression-verdict "
        "events -- both event trails are empty before a first run."),
}


@dataclass
class StartupSubsystemCheck:
    """One subsystem's startup readiness, plus the real evidence behind it --
    the same shape discipline platform_health.SubsystemHealth already
    establishes: `fact_source` names the exact function this check calls, so
    a reader can go verify the claim rather than trust it."""
    subsystem: str
    status: str
    reason: str
    detail: str
    fact_source: str
    observations: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# harness_configuration
# --------------------------------------------------------------------------

def _read_config_file(root: Path) -> Tuple[Optional[dict], Optional[str]]:
    """Reads `.dv-harness/config.json` directly -- never through
    `config.load_config()`, which WRITES a default file to disk the first
    time it is called for a project that has none. Returns
    (parsed_or_None, error_or_None); a file that does not exist is
    (None, None), never an error."""
    p = root / ".dv-harness" / "config.json"
    if not p.is_file():
        return None, None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"could not read {p}: {e}"
    try:
        doc = json.loads(raw)
    except ValueError as e:
        return None, f"{p} is not valid JSON: {e}"
    if not isinstance(doc, dict):
        return None, f"{p} must be a JSON object at the top level, got {type(doc).__name__}"
    return doc, None


def check_config_shape(doc: dict) -> List[Dict[str, str]]:
    """Compares every top-level key `doc` shares with `config.DEFAULT_CONFIG`
    against that default's own shape. Returns a list of findings, each
    `{"field", "severity", "detail"}`. Only two kinds of finding are raised,
    because they are the only two that actually change how the harness
    behaves:

      * MERGE_CORRUPTING (a config.json block is present but is NOT a dict
        where DEFAULT_CONFIG says it should be) -- `config.load_config()`'s
        own merge rule (`if isinstance(v, dict) and isinstance(merged.get(k),
        dict): merged[k].update(v) else: merged[k] = v`) REPLACES the whole
        default block with the scalar/list in this case, silently discarding
        every other field that block was supposed to carry (e.g. a
        config.json declaring `"policy": false` discards
        max_stage_retries/stop_on_blocked/... entirely, with no error).
      * TYPE_MISMATCH (a leaf field's declared type disagrees with the
        default's type) -- reported but never MERGE_CORRUPTING, since the
        merge itself still succeeds; whatever reads that field later may
        behave oddly, but the config file itself is not silently truncated.

    A key `doc` declares that `DEFAULT_CONFIG` does not know about is not a
    finding -- config.load_config()'s own merge keeps it verbatim, and this
    project's own convention (e.g. `configured_by`/`configured_at` inside
    `knowledge_center`) is to carry forward-compatible bookkeeping keys this
    way on purpose."""
    from .config import DEFAULT_CONFIG
    findings: List[Dict[str, str]] = []

    def _walk(path: str, declared: Any, default: Any) -> None:
        if isinstance(default, dict):
            if not isinstance(declared, dict):
                findings.append({
                    "field": path, "severity": "MERGE_CORRUPTING",
                    "detail": (f"{path} is {type(declared).__name__} in config.json but the "
                              f"harness default is a dict -- config.load_config()'s merge rule "
                              f"REPLACES the whole default block with this value rather than "
                              f"merging into it, discarding every field the default block "
                              f"declares")})
                return
            for k, dv in default.items():
                if k in declared:
                    _walk(f"{path}.{k}", declared[k], dv)
            return
        if declared is None or default is None:
            return
        # bool is an int subclass in Python; treat it as its own type so a
        # declared `true`/`false` is never silently accepted where a real
        # number is expected, and vice versa.
        declared_kind = bool if isinstance(declared, bool) else type(declared)
        default_kind = bool if isinstance(default, bool) else type(default)
        numeric = {int, float}
        if declared_kind == default_kind:
            return
        if declared_kind in numeric and default_kind in numeric:
            return
        findings.append({
            "field": path, "severity": "TYPE_MISMATCH",
            "detail": (f"{path} is {declared_kind.__name__} in config.json but the harness "
                      f"default is {default_kind.__name__}")})

    for key, default_value in DEFAULT_CONFIG.items():
        if key in doc:
            _walk(key, doc[key], default_value)
    return findings


def assess_harness_configuration(root: Path) -> StartupSubsystemCheck:
    src = "platform_startup_readiness._read_config_file() + check_config_shape()"
    doc, err = _read_config_file(root)
    if err:
        return StartupSubsystemCheck(
            SUBSYS_HARNESS_CONFIGURATION, BLOCKED, "CONFIG_JSON_UNREADABLE", err, src, {})
    if doc is None:
        return StartupSubsystemCheck(
            SUBSYS_HARNESS_CONFIGURATION, READY, "NO_CONFIG_JSON_YET",
            "no .dv-harness/config.json on disk for this project -- the harness's own real "
            "defaults (config.DEFAULT_CONFIG) apply until one is written", src, {})
    findings = check_config_shape(doc)
    obs = {"findings": findings}
    if any(f["severity"] == "MERGE_CORRUPTING" for f in findings):
        corrupting = [f["field"] for f in findings if f["severity"] == "MERGE_CORRUPTING"]
        return StartupSubsystemCheck(
            SUBSYS_HARNESS_CONFIGURATION, BLOCKED, "CONFIG_BLOCK_WOULD_REPLACE_DEFAULTS",
            f"config.json block(s) {corrupting} would silently REPLACE (not merge into) the "
            f"harness's own default block on load", src, obs)
    if findings:
        mismatched = [f["field"] for f in findings]
        return StartupSubsystemCheck(
            SUBSYS_HARNESS_CONFIGURATION, PARTIAL, "CONFIG_FIELD_TYPE_MISMATCH",
            f"config.json field(s) {mismatched} disagree in type with the harness's own "
            f"default -- the merge still succeeds, but a reader of that field may misbehave",
            src, obs)
    return StartupSubsystemCheck(
        SUBSYS_HARNESS_CONFIGURATION, READY, "CONFIG_JSON_VALID",
        "config.json parses and every field it declares matches the harness's own default "
        "shape", src, obs)


# --------------------------------------------------------------------------
# python_dependencies
# --------------------------------------------------------------------------

def assess_python_dependencies(root: Path) -> StartupSubsystemCheck:
    src = "dependency_supply_chain.build_inventory() + check_declared_vs_installed()"
    from . import dependency_supply_chain as dsc
    try:
        # include_vip=False: a DesignWare VIP install is a per-environment
        # concern this harness's own STARTUP does not depend on -- see
        # env_manifest.py's own three honestly-distinct NOT_AVAILABLE reasons
        # for why an unset $DESIGNWARE_HOME must never be read as a defect.
        inventory = dsc.build_inventory(root=root, include_vip=False)
    except Exception as e:  # a broken pyproject.toml/requirements file must not crash a startup check
        return StartupSubsystemCheck(
            SUBSYS_PYTHON_DEPENDENCIES, UNKNOWN, "DEPENDENCY_INVENTORY_FAILED",
            f"could not build the dependency inventory: {e}", src, {})
    python_components = [c for c in (inventory.get("components") or [])
                        if c.get("ecosystem") == dsc.ECOSYSTEM_PYTHON]
    if not python_components:
        return StartupSubsystemCheck(
            SUBSYS_PYTHON_DEPENDENCIES, READY, "NO_DECLARED_PYTHON_DEPENDENCIES",
            "this project's pyproject.toml/requirements*.txt declare no Python dependency -- "
            "nothing to check", src, {"component_count": 0})
    result = dsc.check_declared_vs_installed(inventory)
    declared_names = {c.get("name") for c in python_components}
    missing = sorted({
        f.get("component") for f in (result.get("findings") or [])
        if f.get("kind") == dsc.FINDING_NOT_INSTALLED and f.get("component") in declared_names})
    obs = {"declared": sorted(str(n) for n in declared_names), "missing": missing,
          "resolution_counts": result.get("counts")}
    if missing:
        return StartupSubsystemCheck(
            SUBSYS_PYTHON_DEPENDENCIES, BLOCKED, "DECLARED_DEPENDENCY_NOT_INSTALLED",
            f"{len(missing)} declared Python dependency(ies) not installed for this "
            f"interpreter: {missing}", src, obs)
    return StartupSubsystemCheck(
        SUBSYS_PYTHON_DEPENDENCIES, READY, "ALL_DECLARED_DEPENDENCIES_INSTALLED",
        f"every one of {len(declared_names)} declared Python dependency(ies) resolves for this "
        f"interpreter", src, obs)


# --------------------------------------------------------------------------
# agent_adapter (startup-specific: command resolvability, not recorded
# degradation history)
# --------------------------------------------------------------------------

def assess_agent_adapter(cfg: dict) -> StartupSubsystemCheck:
    src = "adapters.cli.ClaudeCLIAdapter._resolve_command()"
    adapter_kind = cfg.get("adapter", "cli")
    if adapter_kind != "cli":
        return StartupSubsystemCheck(
            _platform_health.SUBSYS_AGENT_ADAPTER, UNKNOWN, "UNRECOGNIZED_ADAPTER_KIND",
            f"config.adapter={adapter_kind!r} is not the 'cli' adapter this check knows how "
            f"to verify -- this harness currently ships only ClaudeCLIAdapter", src, {})
    from .adapters.cli import ClaudeCLIAdapter
    configured = (cfg.get("claude") or {}).get("command") or "claude"
    resolved = ClaudeCLIAdapter._resolve_command(configured)
    obs = {"configured": configured, "resolved": resolved}
    if resolved == configured and shutil.which(configured) is None and not Path(configured).is_file():
        return StartupSubsystemCheck(
            _platform_health.SUBSYS_AGENT_ADAPTER, BLOCKED, "AGENT_ADAPTER_COMMAND_NOT_RESOLVABLE",
            f"config.claude.command={configured!r} resolves to neither a PATH entry "
            f"(shutil.which) nor an existing file -- no stage could ever dispatch an agent",
            src, obs)
    return StartupSubsystemCheck(
        _platform_health.SUBSYS_AGENT_ADAPTER, READY, "AGENT_ADAPTER_COMMAND_RESOLVABLE",
        f"config.claude.command={configured!r} resolves to {resolved!r}", src, obs)


# --------------------------------------------------------------------------
# execution_preflight_configuration (folds platform_health's eda_license /
# lsf_queue / execution_environment subsystems into the one thing checkable
# without a live probe: does the preflight config block's own SHAPE let
# preflight.py's real checks run at all)
# --------------------------------------------------------------------------

def check_preflight_config_shape(pf_cfg: "Any") -> List[str]:
    """Real type findings against a real `preflight.PreflightConfig`
    instance -- never a live lmstat/bqueues probe. An empty
    `license_server`/`workdir` is NEVER a finding here: config.py's own
    comment documents that as the normal state for a project that has not
    yet been pointed at a real remote server, and `preflight.py`'s own
    `require_license_configured` is what decides whether that blocks a real
    submission -- a decision this module does not make."""
    findings: List[str] = []
    if not isinstance(pf_cfg.required_env_vars, list) or not all(
            isinstance(v, str) and v for v in pf_cfg.required_env_vars):
        findings.append(
            f"preflight.required_env_vars must be a list of non-empty strings, got "
            f"{pf_cfg.required_env_vars!r}")
    if not isinstance(pf_cfg.license_features, list) or not all(
            isinstance(v, str) and v for v in pf_cfg.license_features):
        findings.append(
            f"preflight.license_features must be a list of non-empty strings, got "
            f"{pf_cfg.license_features!r}")
    if isinstance(pf_cfg.min_free_disk_gb, bool) or not isinstance(
            pf_cfg.min_free_disk_gb, (int, float)) or pf_cfg.min_free_disk_gb <= 0:
        findings.append(
            f"preflight.min_free_disk_gb must be a positive number, got "
            f"{pf_cfg.min_free_disk_gb!r}")
    for field_name in ("queue", "workdir", "license_server", "lmutil_path", "shell"):
        v = getattr(pf_cfg, field_name)
        if not isinstance(v, str):
            findings.append(f"preflight.{field_name} must be a string, got {v!r}")
    return findings


def assess_execution_preflight_configuration(cfg: dict) -> StartupSubsystemCheck:
    src = "preflight.config_from_dict() + check_preflight_config_shape()"
    ep_cfg = cfg.get("execution_preflight") or {}
    if not ep_cfg.get("enabled", True):
        return StartupSubsystemCheck(
            SUBSYS_EXECUTION_PREFLIGHT_CONFIG, NOT_APPLICABLE_AT_STARTUP,
            "EXECUTION_PREFLIGHT_DISABLED",
            "config.execution_preflight.enabled is false -- this project's config does not "
            "intend to run the license/queue/host-environment preflight gate at all", src, {})
    from . import preflight
    try:
        pf_cfg = preflight.config_from_dict(cfg.get("preflight") or {})
    except Exception as e:  # a malformed preflight block must not crash a startup check
        return StartupSubsystemCheck(
            SUBSYS_EXECUTION_PREFLIGHT_CONFIG, BLOCKED, "PREFLIGHT_CONFIG_UNBUILDABLE",
            f"could not build a PreflightConfig from config.json's preflight block: {e}", src, {})
    findings = check_preflight_config_shape(pf_cfg)
    if findings:
        return StartupSubsystemCheck(
            SUBSYS_EXECUTION_PREFLIGHT_CONFIG, BLOCKED, "PREFLIGHT_CONFIG_SHAPE_INVALID",
            f"{len(findings)} real type problem(s) in config.json's preflight block would "
            f"break preflight.py's own checks at run time", src, {"findings": findings})
    return StartupSubsystemCheck(
        SUBSYS_EXECUTION_PREFLIGHT_CONFIG, READY, "PREFLIGHT_CONFIG_SHAPE_VALID",
        "config.json's preflight block builds a real PreflightConfig whose fields are all "
        "correctly typed for preflight.py's own checks (whether license_server/workdir are "
        "filled in is a separate, non-blocking fact -- see this function's own docstring)",
        src, {})


# --------------------------------------------------------------------------
# project_state_directory
# --------------------------------------------------------------------------

def assess_project_state_directory(root: Path) -> StartupSubsystemCheck:
    src = "platform_startup_readiness.assess_project_state_directory()"
    state_dir = root / ".dv-harness"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".startup_readiness_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return StartupSubsystemCheck(
            SUBSYS_PROJECT_STATE_DIRECTORY, BLOCKED, "STATE_DIRECTORY_NOT_WRITABLE",
            f"{state_dir} could not be created and/or written to: {e}", src, {"path": str(state_dir)})
    return StartupSubsystemCheck(
        SUBSYS_PROJECT_STATE_DIRECTORY, READY, "STATE_DIRECTORY_WRITABLE",
        f"{state_dir} exists (or was created) and a real write+delete probe succeeded",
        src, {"path": str(state_dir)})


# --------------------------------------------------------------------------
# platform_health subsystems this module explicitly, honestly excludes
# --------------------------------------------------------------------------

def _not_applicable_checks() -> List[StartupSubsystemCheck]:
    out = []
    for subsys, reason in _NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS.items():
        out.append(StartupSubsystemCheck(
            subsys, NOT_APPLICABLE_AT_STARTUP, "NEEDS_OPERATIONAL_HISTORY", reason,
            "platform_health.py", {}))
    return out


def assert_reuses_platform_health_taxonomy() -> None:
    """Every subsystem id this module folds or excludes must be a REAL
    `platform_health.SUBSYSTEMS` member -- this is the module-level assertion
    that this module actually iterates platform_health's own taxonomy rather
    than a silently-drifted copy of it. Run at import."""
    covered = set(_STARTUP_CHECKABLE_PLATFORM_HEALTH_SUBSYSTEMS) | set(
        _NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS)
    known = set(_platform_health.SUBSYSTEMS)
    if covered != known:
        raise AssertionError(
            f"platform_startup_readiness must account for every platform_health.SUBSYSTEMS "
            f"member exactly once; covered={sorted(covered)} known={sorted(known)}")


assert_reuses_platform_health_taxonomy()


# --------------------------------------------------------------------------
# The one report
# --------------------------------------------------------------------------

def startup_readiness_report(root) -> dict:
    """The whole startup-readiness picture as one JSON-serializable dict.
    Read-only end to end except for `assess_project_state_directory()`'s own
    throwaway write+delete probe."""
    root = Path(root)
    cfg, cfg_err = _read_config_file(root)
    merged_cfg = cfg if isinstance(cfg, dict) else {}

    checks: List[StartupSubsystemCheck] = [
        assess_harness_configuration(root),
        assess_python_dependencies(root),
        assess_agent_adapter(merged_cfg),
        assess_execution_preflight_configuration(merged_cfg),
        assess_project_state_directory(root),
    ]
    checks.extend(_not_applicable_checks())

    applicable = [c for c in checks if c.status != NOT_APPLICABLE_AT_STARTUP]
    overall = combine_readiness([c.status for c in applicable])

    return {
        "project_root": str(root),
        "overall_status": overall,
        "subsystems": [c.to_dict() for c in checks],
        "state_counts": {
            st: sum(1 for c in checks if c.status == st)
            for st in (READY, PARTIAL, BLOCKED, UNKNOWN, NOT_APPLICABLE_AT_STARTUP)
        },
        "authorizes_nothing": ("read-only startup check: no stage run, no build, no LSF "
                               "submission, no approval consulted or granted"),
    }


def render_report_text(report: dict) -> str:
    lines = [f"DV Agent Harness L5 -- platform startup readiness ({report['project_root']})",
             f"OVERALL: {report['overall_status']}", ""]
    lines.append(f"{'SUBSYSTEM':<32}{'STATUS':<24}REASON")
    lines.append("-" * 90)
    for s in report["subsystems"]:
        lines.append(f"{s['subsystem']:<32}{s['status']:<24}{s['reason']}")
        lines.append(f"{'':<32}{'':<24}{s['detail']}")
        lines.append(f"{'':<32}{'':<24}source: {s['fact_source']}")
    lines += ["", report["authorizes_nothing"]]
    return "\n".join(lines)


_EXIT_BY_OVERALL: Dict[str, int] = {READY: 0, BLOCKED: 1, PARTIAL: 2, UNKNOWN: 2}


def execute(root) -> Tuple[int, dict, str]:
    """(exit_code, report, text) -- the one shared implementation behind
    `python -m dv_harness.platform_startup_readiness`, matching the shape
    `platform_health.execute()` already uses. Exit 0 READY, 1 BLOCKED (the
    harness cannot safely start), 2 PARTIAL/UNKNOWN (something is incomplete
    but not a hard block)."""
    report = startup_readiness_report(root)
    text = render_report_text(report)
    return _EXIT_BY_OVERALL.get(report["overall_status"], 2), report, text


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.platform_startup_readiness",
        description="Startup-time check: is this harness correctly configured, are its "
                    "declared Python dependencies present, is config.json valid -- distinct "
                    "from `dv-harness platform-health`'s ongoing operational aggregator. "
                    "Read-only except for a throwaway write+delete probe of "
                    ".dv-harness/'s own writability.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    code, report, text = execute(root)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
