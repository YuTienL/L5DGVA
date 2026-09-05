"""CREATE ENVIRONMENT dispatch: the missing wire between
environment_mode_router.resolve_environment_mode() and the two real
generators it is supposed to be choosing between (2026-09-04,
AI-mechanism re-audit gap #14 "Subsystem -> System-Level/SoC verification
generation").

What was actually wrong (real evidence, re-verified before this module was
written -- not a restatement of an older report):

  - CLAUDE.md's "Environment Generation Mode" section requires a
    SUBSYSTEM_MODE / SYSTEM_LEVEL_MODE selection BEFORE CREATE ENVIRONMENT,
    and .dv-harness/environment-router/environment_mode_policy.json carries
    "mode_must_be_explicit_before_generation": true.
  - resolve_environment_mode() really computes that decision, and
    engine.py's begin_stage() really calls it on every stage -- but its
    result landed only in route_info["environment_mode_decision"], i.e. in
    the prompt and the ReAct record. Nothing branched on it.
  - The one official generation entry point is
    tools/generate_protocol_uvm_environment.py ->
    ProtocolEnvGenerator.generate() (see generator.py's own header NOTICE,
    and every .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md, all ten of which
    invoke exactly that script). It took a manifest and generated a
    single-protocol environment unconditionally: grepping
    protocol_env_generator.py for "environment_mode" or
    "soc_environment_composer" returned nothing. A genuine
    SYSTEM_LEVEL_MODE request -- two or more
    subsystems, already registered -- silently produced ONE subsystem
    environment, and compose_soc_environment() fired only if an agent
    happened to know to hand-assemble a system_level_validator evidence
    block for the SYSTEM_LEVEL stage instead.

This module closes that: it is the branch point, and it reuses the three
real pieces that already exist rather than reimplementing any of them --
resolve_environment_mode() for the decision, ProtocolEnvGenerator for
SUBSYSTEM_MODE, compose_soc_environment() for SYSTEM_LEVEL_MODE.

Three deliberate properties:

1. **SUBSYSTEM_MODE stays byte-identical.** A manifest carrying `protocol`
   and no `requested_subsystems` -- exactly what every PROTOCOL_BUILDERS
   skill passes today -- resolves to SUBSYSTEM_MODE and reaches the same
   `ProtocolEnvGenerator(out).generate(m)` call with the same argument. This
   is a new branch in front of the existing path, never a rewrite of it.

2. **The composed subsystems come from the REAL registry, never from the
   caller.** SYSTEM_LEVEL_MODE composition reads full entries off
   .dv-harness/soc-composer/subsystem_environment_registry.json
   (read_registered_subsystem_entries()), which only engine.py's
   _persist_subsystem_registry_entry() writes, and only on a real
   SIGNOFF PASS whose subsystem_environment_registration_gate already
   validated the entry. A caller cannot inject an unregistered subsystem
   into a composition through this path -- the same guarantee
   system_level_validator.py's harness-supplied --registered cross-check
   gives on the SYSTEM_LEVEL stage path.

3. **SUBSYSTEM_MODE also layers the protocol's OWN model (2026-09-04,
   re-audit gap #13 "Generic multi-protocol DV Harness scope").** Dispatching
   the mode correctly still produced the same protocol-agnostic skeleton for
   every protocol, because the five real protocol-model generators in this
   package were reachable only from five standalone tools. `protocol_model_
   layer.py` is that wire; see its module docstring. It changes nothing for a
   protocol with no model (USB) or a manifest with no `protocol_model_
   topology`, beyond recording which of those two it was.

4. **A missing subsystem REFUSES rather than degrading.** CLAUDE.md: "If a
   required subsystem is missing in SYSTEM_LEVEL_MODE, build it through
   SUBSYSTEM_MODE then return to composition." Quietly generating one
   subsystem environment for a two-subsystem request, or composing whatever
   subset happens to be registered, would both misreport a partial result as
   the requested one. SubsystemModeRequiredError carries the router's own
   `missing_subsystems` and `next_action` so the caller is told which build
   to run first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import json

from ..environment_mode_router import (
    resolve_environment_mode,
    read_registered_subsystem_entries,
)
from ..uvm_structural_lint import format_report, lint_uvm_environment
from ..vip_api_card import (
    VIP_API_CARDS_REPORT_NAME,
    VipApiValidationError,
    format_report as format_vip_api_report,
    load_index as load_vip_symbol_index,
    validate_vip_api_usage,
    write_vip_api_cards,
)
from .generator import sv_id
from .protocol_env_generator import ProtocolEnvGenerator
from .protocol_model_layer import (
    add_protocol_model_to_filelist,
    emit_protocol_model_files,
    inject_state_machine_checks,
    plan_protocol_model,
)
from .soc_environment_composer import compose_soc_environment, soc_composition_out_dir


class EnvironmentModeUnresolvedError(ValueError):
    """Raised when the request names nothing to build -- no
    `requested_subsystems` and no `protocol`. Same typed-error convention as
    soc_environment_composer.py's EmptySubsystemRegistryError: a
    SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict.

    Deliberately an error rather than a default: environment_mode_policy.json
    sets "mode_must_be_explicit_before_generation": true, and
    resolve_environment_mode() itself returns resolved=False with
    MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION for this input rather than
    guessing a mode. Picking SUBSYSTEM_MODE here "because it is the common
    case" would reintroduce exactly the unstated default that gate forbids."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class MissingOutputDirectoryError(ValueError):
    """Raised when SUBSYSTEM_MODE resolves but no out_dir was given. Its own
    type, not an EnvironmentModeUnresolvedError: the mode WAS resolved, and
    conflating "you did not say what to build" with "you did not say where to
    put it" would make the caller's two very different fixes look like one
    failure. There is no project-wide convention for where a single protocol
    environment lands -- the caller has always chosen it, via the tool's
    --out -- so this is not defaultable the way SYSTEM_LEVEL_MODE's
    generated/soc_composition/<soc_name>/ is."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class SubsystemModeRequiredError(ValueError):
    """Raised when SYSTEM_LEVEL_MODE resolves but one or more requested
    subsystems are not in the real registry (router's
    needs_subsystem_mode_first). Carries `missing_subsystems` and the
    router's own `next_action` string, so the caller learns which
    SUBSYSTEM_MODE build to run before returning to composition."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class StructuralLintFailedError(ValueError):
    """Raised only when the request opted in with `strict_structural_lint:
    true` AND the post-generation structural lint found ERROR-severity
    defects. Default behaviour is non-blocking: the environment is still
    written and the report is still recorded, because this lint is new and
    must not turn a previously-working generation into a hard failure without
    the caller asking for that. Carries the full report dict on `.detail`."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class VipApiUnprovableError(ValueError):
    """Raised only when the request opted in with `strict_vip_api: true` AND the
    post-generation VIP API validation found BLOCKED citations -- a generated
    sequence calling a VIP class/method the real `vip_symbol_index` cannot prove
    exists. Section 187's own stop condition ("If API cannot be proven:
    UNKNOWN / BLOCKED") as a raised error rather than prose.

    Default behaviour is non-blocking, for the same reason
    StructuralLintFailedError's is, plus one specific to this check: its single
    false-positive risk is an incomplete
    `vip_api_card.BASE_LIBRARY_METHODS` allowlist, and a new check must not turn
    a previously-working generation into a hard failure without the caller
    asking for that. Carries the full report on `.detail`."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


STRUCTURAL_LINT_REPORT_NAME = "uvm_structural_lint.json"


def _run_structural_lint(out_dir: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic structural lint of the UVM code THIS call just generated,
    run here because this is the last point before the environment leaves for a
    compile/simulation -- section 220's "Structural lint runs before expensive
    simulation where possible".

    The report is always written to <out_dir>/uvm_structural_lint.json so the
    evidence survives the process, and always returned so the caller can print
    it. A verible that cannot be run yields status NOT_AVAILABLE with a real
    reason (uvm_structural_lint never fabricates a PASS it could not check),
    and that is not a generation failure -- verible is not a build dependency
    of this generator.

    Set `strict_structural_lint: true` in the request to make ERROR-severity
    findings raise StructuralLintFailedError instead."""
    report = lint_uvm_environment(out_dir)
    payload = report.to_dict()
    try:
        (Path(out_dir) / STRUCTURAL_LINT_REPORT_NAME).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        # Recording the report must never destroy an otherwise-good
        # generation; the report is still returned in-process.
        payload["report_write_error"] = str(exc)
    if request.get("strict_structural_lint") and payload["status"] == "FAIL":
        raise StructuralLintFailedError("UVM_STRUCTURAL_LINT_FAILED", {
            "out_dir": str(out_dir),
            "report": payload,
            "summary": format_report(report),
        })
    return payload


def _run_vip_api_validation(out_dir: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    """Spec section 187's `Validate Signature -> VIPApiCard` step, run over the
    sequences THIS call just generated and the REAL VIP symbol index the
    request names.

    Runs only when the request carries `vip_symbol_index: <path>`. That is a
    deliberate opt-in rather than a discovered default: the index must be an
    index of the VIP this environment actually binds, and validating an
    environment against some other VIP's index would report every real call as
    unprovable. Absent that path the result is NOT_AVAILABLE with a real reason
    -- never PROVEN, because "we could not check" must not read as "checked and
    clean".

    The VIPApiCard artifact is always written to <out_dir>/vip_api_cards.json
    so the evidence survives the process, and always returned. Set
    `strict_vip_api: true` to make BLOCKED citations raise
    VipApiUnprovableError instead of being recorded and returned."""
    index_path = request.get("vip_symbol_index")
    if not index_path:
        return {
            "status": "NOT_AVAILABLE",
            "reason": "NO_VIP_SYMBOL_INDEX_DECLARED_IN_REQUEST",
            "detail": ("set `vip_symbol_index: <path to a vip_symbol_index.json>` in the "
                       "generation manifest to have every generated VIP API call checked "
                       "against the real indexed VIP source (spec section 187)"),
        }
    try:
        index = load_vip_symbol_index(index_path)
    except VipApiValidationError as exc:
        # A mistyped index path must not silently disable the check.
        return {"status": "NOT_AVAILABLE", "reason": "VIP_SYMBOL_INDEX_UNREADABLE",
                "detail": str(exc)}

    report = validate_vip_api_usage([out_dir], index, relative_to=out_dir)
    payload = report.to_dict()
    try:
        write_vip_api_cards(report, out_dir)
    except OSError as exc:
        payload["report_write_error"] = str(exc)
    if request.get("strict_vip_api") and payload["status"] == "BLOCKED":
        raise VipApiUnprovableError("VIP_API_UNPROVABLE_BLOCKED", {
            "out_dir": str(out_dir),
            "report": payload,
            "summary": format_vip_api_report(report),
        })
    return payload


def _requested_subsystems(request: Dict[str, Any]) -> List[str]:
    """What this CREATE ENVIRONMENT request is asking to build, as
    resolve_environment_mode()'s `requested_subsystems` input.

    Explicit `requested_subsystems` wins (the SYSTEM_LEVEL composition
    shape). Otherwise a single-protocol manifest's own `protocol` field IS
    the one requested subsystem -- that is what makes an unchanged
    PROTOCOL_BUILDERS manifest resolve SUBSYSTEM_MODE through the real
    router instead of bypassing the decision entirely."""
    explicit = request.get("requested_subsystems")
    if explicit:
        return [str(s) for s in explicit]
    protocol = request.get("protocol")
    return [str(protocol)] if protocol else []


def create_environment(root: Path, request: Dict[str, Any],
                       out_dir: Optional[Path] = None) -> Dict[str, Any]:
    """The real CREATE ENVIRONMENT entry point: resolve the mode from real
    evidence, then dispatch to the generator that mode names.

    Args:
      root: project root -- where the real subsystem registry is read from
        (.dv-harness/soc-composer/subsystem_environment_registry.json) and,
        absent an explicit out_dir, where a SYSTEM_LEVEL_MODE composition is
        written (generated/soc_composition/<soc_name>/, the SAME path
        engine.py's _compose_soc_environment_files() uses -- both call
        soc_composition_out_dir()).
      request: the generation manifest. SUBSYSTEM_MODE passes it through to
        ProtocolEnvGenerator.generate() unchanged; SYSTEM_LEVEL_MODE passes
        it through to compose_soc_environment() as the composition
        `manifest` (soc_name/shared_clocks/shared_resets/
        cross_subsystem_scenarios/... -- soc_composition_manifest_template
        .json's own schema), reusing the one dict rather than inventing a
        second request schema.
      out_dir: explicit output directory. REQUIRED for SUBSYSTEM_MODE (there
        is no project-wide convention for where one protocol environment
        lands -- the caller has always chosen it, via the tool's --out);
        optional for SYSTEM_LEVEL_MODE.

    Returns a dict carrying `environment_mode`, the full router `decision`
    (so a caller can log WHY this mode was chosen, not just which), the
    `out_dir` written to, and `generated_files`. SUBSYSTEM_MODE additionally
    carries `protocol_model` (the layering record, also written into the
    generated environment_manifest.json) and `protocol_model_files`;
    SYSTEM_LEVEL_MODE additionally carries `composed_subsystems`. BOTH modes
    carry `structural_lint`, the deterministic pre-simulation lint of the UVM
    code just generated (see _run_structural_lint()), and
    `vip_api_validation`, spec section 187's VIPApiCard check of every VIP API
    call in that code against the real VIP symbol index (see
    _run_vip_api_validation()).

    Raises EnvironmentModeUnresolvedError / MissingOutputDirectoryError /
    SubsystemModeRequiredError / StructuralLintFailedError /
    VipApiUnprovableError (see their docstrings),
    protocol_model_layer.ProtocolModelLayerError when a supplied
    protocol_model_topology is refused by that protocol's own model, or
    propagates compose_soc_environment()'s own
    NotImplementedError for the genuinely protocol-specific
    cross_subsystem_scenarios/end_to_end_scoreboards/system_coverage content
    it deliberately refuses to fabricate."""
    root = Path(root)
    requested = _requested_subsystems(request)
    registered_entries = read_registered_subsystem_entries(root)
    decision = resolve_environment_mode({
        "requested_subsystems": requested,
        "existing_registered_subsystems": [e["name"] for e in registered_entries],
    })

    if not decision.get("resolved"):
        raise EnvironmentModeUnresolvedError(decision.get("reason", "MODE_UNRESOLVED"), {
            "decision": decision,
            "request_keys": sorted(request.keys()),
        })

    if decision["environment_mode"] == "SUBSYSTEM_MODE":
        if out_dir is None:
            raise MissingOutputDirectoryError("SUBSYSTEM_MODE_REQUIRES_OUT_DIR", {
                "decision": decision,
            })
        # ProtocolEnvGenerator.generate() keys every emitted identifier off
        # m["protocol"]. A manifest that named its one subsystem only as
        # requested_subsystems=["USB"] (legal input to the router, and the
        # shape a caller reaches for after writing a two-subsystem request)
        # would otherwise KeyError here. The single resolved requested
        # subsystem IS that protocol -- filled in only when `protocol` is
        # genuinely absent, so a manifest that carries one is never
        # overridden.
        manifest = dict(request)
        manifest.setdefault("protocol", decision["requested_subsystems"][0])
        # SUBSYSTEM_MODE builds the protocol's OWN environment, so this is
        # where the protocol's own model belongs -- see protocol_model_layer.py
        # for what was wrong before it (five real, unit-tested protocol models
        # whose only non-test callers were five standalone tools). The plan is
        # computed and recorded for EVERY protocol, including the ones with no
        # model, so a generated environment always states which of the two it
        # is instead of leaving it to be inferred from an absence.
        protocol_model = plan_protocol_model(manifest)
        # The model runs BEFORE the skeleton, so a topology its own validator
        # refuses leaves no half-written environment behind, and so the
        # emitted file list is in the record ProtocolEnvGenerator serialises
        # into environment_manifest.json. Only the filelist step waits, since
        # there is no filelist until the skeleton is written.
        model_files = emit_protocol_model_files(out_dir, manifest, protocol_model)
        inject_state_machine_checks(manifest, protocol_model)
        manifest["protocol_model"] = protocol_model
        generated = ProtocolEnvGenerator(out_dir).generate(manifest)
        add_protocol_model_to_filelist(out_dir, model_files)
        return {
            "environment_mode": "SUBSYSTEM_MODE",
            "decision": decision,
            "out_dir": str(out_dir),
            "generated_files": generated,
            "protocol_model": protocol_model,
            "protocol_model_files": model_files,
            "structural_lint": _run_structural_lint(out_dir, request),
            "vip_api_validation": _run_vip_api_validation(Path(out_dir), request),
        }

    # --- SYSTEM_LEVEL_MODE ---
    if decision.get("needs_subsystem_mode_first"):
        raise SubsystemModeRequiredError("SUBSYSTEM_MODE_REQUIRED_FIRST", {
            "missing_subsystems": decision.get("missing_subsystems", []),
            "next_action": decision.get("next_action"),
            "decision": decision,
        })

    # Compose from the REAL registered entries, matched by name against what
    # was requested (case-insensitively, the same way the router itself
    # compares them), and ordered by the REQUEST -- so the generated
    # soc_tb_top.sv instantiates the subsystems in the order the composition
    # asked for, not in registry-write order.
    by_name = {str(e["name"]).lower(): e for e in registered_entries}
    subsystems = [by_name[s.lower()] for s in decision["requested_subsystems"]]

    # `root` is passed so the composition consults the REAL cross-subsystem
    # analysis (SYS-9..SYS-14) before composing, instead of composing blind to
    # it -- a CrossSubsystemIntegrationBlockedError propagates to the caller
    # exactly like SubsystemModeRequiredError above, and needs the same thing:
    # a human decision, here on which subsystem owns the contended interface.
    files = compose_soc_environment(subsystems, request, root)
    target = Path(out_dir) if out_dir is not None else soc_composition_out_dir(
        root, request.get("soc_name"))
    target.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (target / name).write_text(content, encoding="utf-8")
    return {
        "environment_mode": "SYSTEM_LEVEL_MODE",
        "decision": decision,
        "out_dir": str(target),
        "generated_files": sorted(files.keys()),
        "composed_subsystems": [s["name"] for s in subsystems],
        "soc_name": sv_id(request.get("soc_name") or "soc"),
        "structural_lint": _run_structural_lint(target, request),
        "vip_api_validation": _run_vip_api_validation(target, request),
    }
