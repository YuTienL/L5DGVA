"""SYSTEM_LEVEL_MODE real composer (added 2026-09-01, protocol-genericity
audit follow-up).

Background / what this closes: the 2026-09-01 protocol-genericity audit
found SYSTEM_LEVEL_MODE is a real, code-backed GATE (dv_harness/dashboard.py,
tools/verification_flow/subsystem_environment_registration_gate.py,
tools/real_env/system_level_validator.py are all real, all wired into
dv_harness/gates.py's STAGE_GATES["SYSTEM_LEVEL"]) but had ZERO generator
code behind it: WORKFLOW_MANIFEST.json claims
"system_level_scoreboard_composer": true / "system_level_coverage_composer":
true, and PROTOCOL_SUPPORT_MATRIX-adjacent docs describe a
"soc_system_level_environment_composer", but before this module those were
unbacked string literals -- grepping dv_harness/uvm_generator/generator.py
for "system_level"/"soc_tb_top"/"cross_subsystem" returned zero matches.
This module is the real generator code. It is deliberately scoped to what
IS genuinely generic: composing ALREADY-REGISTERED, already-qualified
subsystem environments (whatever protocol each one is -- this module never
branches on a protocol name) into a Full-SoC/System-Level testbench
scaffold. It reuses generator.py's own per-subsystem naming convention
(`<protocol>_env`, `<protocol>_env_pkg`, `<protocol>_virtual_sequencer` --
see UVMEnvironmentGenerator.env()/pkg()/vseq()) and its own
virtual_sequencer_fields DSL (UVMEnvironmentGenerator.vseq(), reused here
verbatim, not reinvented) rather than inventing a parallel schema.

Real, honest boundary (CLAUDE.md "No Golden-Reference Content Mining" /
"if genuinely blocked on missing real-world evidence... leave a clearly
-commented NotImplementedError... do not invent a plausible-looking fake
implementation"): cross-subsystem SCENARIO bodies, an end-to-end scoreboard
that actually checks data crossing two-plus subsystems, and system-level
coverage bins are genuine protocol-BEHAVIOR content -- exactly the category
CLAUDE.md requires be sourced from PRIMARY evidence (VIP examples/user
manual/source/class reference, or DUT RTL/PHY docs/programming guide) for
the SPECIFIC subsystems being composed. A subsystem_environment_registry
entry carries only identity/qualification metadata (name, release_sha,
qualification_state, interface/clock-reset compatibility flags) -- never
sequence-body semantics -- so a generic composer has no primary source to
draw that content from. cross_subsystem_scenarios()/end_to_end_scoreboard()/
system_coverage() below therefore always raise NotImplementedError with a
clear explanation, rather than emit a plausible-looking placeholder body.
See CREATE_ENVIRONMENT.md / SOC_SYSTEM_LEVEL_COMPOSER.md for how a future
per-composition-session agent is expected to supply that content from real
per-subsystem VIP/DUT evidence once it exists; this module's job stops at
the generic, protocol-blind structural composition.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .generator import sv_id, UVMEnvironmentGenerator

# dv_harness/uvm_generator/soc_environment_composer.py -> dv_harness/uvm_generator
# -> dv_harness -> <repo root>. Used only as a best-effort base to resolve a
# registry entry's "environment_manifest" path (see _resolve_subsystem_manifest
# below) -- never required, never trusted as evidence on its own.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class EmptySubsystemRegistryError(ValueError):
    """Raised by compose_soc_environment when subsystem_registry_entries is
    empty/absent. Same typed-error convention as generator.py's
    CircularDependencyError/UnknownDependencyError/MissingConnectionEvidenceError:
    a short SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict.
    SYSTEM_LEVEL_MODE composes registered subsystems -- with none supplied
    there is nothing to compose, and silently emitting an empty tb_top would
    misrepresent an unqualified no-op as a real composition."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class MissingSubsystemNameEvidenceError(ValueError):
    """Raised by compose_soc_environment when a subsystem_registry_entries
    item has no non-empty "name" -- the one field this module strictly
    requires, since every generated identifier (module/class/package name,
    virtual-sequencer field name) is derived from it via the same sv_id()
    normalization generator.py's own per-subsystem generation already uses.
    (The FULL required-field set -- environment_manifest/release_sha/
    qualification_state/interface_compatibility/clock_reset_compatibility --
    is already enforced by
    tools/verification_flow/subsystem_environment_registration_gate.py
    BEFORE a real entry is ever persisted into
    .dv-harness/soc-composer/subsystem_environment_registry.json; RULING:
    re-enforcing that whole set here would be redundant defense-in-depth
    against a registry this module trusts was already gate-validated, not
    new protection, and would reject legitimate minimal test fixtures this
    module's own genericity is meant to support. Missing optional fields
    degrade gracefully to an "UNKNOWN" citation in generated evidence
    comments instead of hard-failing -- see _cite() below.)"""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class CrossSubsystemIntegrationBlockedError(ValueError):
    """Raised by compose_soc_environment() when the REAL cross-subsystem
    analysis (dv_harness.system_resource_inventory's SYS-9..SYS-14 chain,
    reached through real_cross_subsystem_findings()) says automatic
    integration of these subsystems is STOPPED or HELD -- two ACTIVE agents
    independently driving one physical interface, or an unproven-but-both-
    active pair.

    Before 2026-09-05 this composer imported none of that analysis and
    composed BLIND to it: a soc_tb_top.sv instantiating two subsystem
    environments whose CPU AXI masters both drive `chip.soc.cpu_axi_m` was
    generated without complaint. It now refuses.

    Refusing is the whole behaviour -- this error carries the conflicting
    resource ids and SYS-12's preferred model as text for a HUMAN to
    arbitrate ownership from. Nothing here picks a winner between two
    conflicting drivers; that decision is not a generator's to make (see
    system_resource_inventory.SYS12_PREFERRED_MODEL, and SYS-39/SYS-40's own
    approval boundary before any shared driver is generated for real)."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def soc_composition_out_dir(root: Path, soc_name: Any) -> Path:
    """The one on-disk location a composed SoC environment lands in, in one
    place. Both real writers use it: engine.py's
    _compose_soc_environment_files() (SYSTEM_LEVEL stage PASS) and
    create_environment.py's SYSTEM_LEVEL_MODE dispatch (the CREATE
    ENVIRONMENT entry point) -- so a composition produced through either
    real path is found at the same path by the other, instead of two call
    sites each hardcoding their own `generated/soc_composition/...` string."""
    return Path(root) / "generated" / "soc_composition" / sv_id(soc_name or "soc")


def _cite(entry: Dict[str, Any]) -> str:
    """One evidence-comment fragment identifying a registered subsystem by
    its real registry identity -- reused everywhere this module emits a
    `// evidence: ...` line or a virtual_sequencer_fields "evidence" string,
    same evidence-required discipline generator.py's own _connect_phase/vseq
    already enforce for every generated wire-up/field."""
    return (
        f"registered subsystem '{entry.get('name')}' "
        f"(release_sha={entry.get('release_sha', 'UNKNOWN')}, "
        f"qualification_state={entry.get('qualification_state', 'UNKNOWN')}) "
        "from .dv-harness/soc-composer/subsystem_environment_registry.json"
    )


def _resolve_subsystem_manifest(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort read of the real per-subsystem environment_manifest.json
    a registry entry's "environment_manifest" field points at -- the SAME
    file UVMEnvironmentGenerator.generate() itself writes (see its own
    `files['environment_manifest.json']=json.dumps(manifest,...)`), so a
    real registered subsystem's actual clocks/resets are read from real
    generation evidence, never guessed. Returns {} (not a fabricated
    manifest) when the field is absent, or the path does not resolve to a
    real readable JSON file -- e.g. a synthetic/unit-test registry entry
    whose "environment_manifest" path was never actually generated on disk.
    Callers fall back to a generic per-subsystem default in that case (see
    _collect_clocks_resets below), the same defensive-default pattern
    generator.py's own tb_top() already uses
    (`(m.get('clocks') or [{'name':'clk'}])[0]`) -- never an invented
    fabricated evidence string claiming a file that isn't really there."""
    rel = entry.get("environment_manifest")
    if not rel:
        return {}
    path = Path(rel)
    if not path.is_absolute():
        path = _REPO_ROOT / rel
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _collect_clocks_resets(subsystems: List[Dict[str, Any]], manifest: Dict[str, Any]):
    """Real per-subsystem clock/reset names for soc_tb_top.sv, in priority
    order:
      1. manifest["shared_clocks"]/["shared_resets"] (soc_composition_manifest
         schema fields -- see .dv-harness/soc-composer/
         soc_composition_manifest_template.json) when the composition
         author already curated a shared clock/reset plan.
      2. otherwise, each subsystem's OWN real clocks/resets, read from its
         real environment_manifest.json via _resolve_subsystem_manifest
         (deduplicated by name -- two subsystems sharing a clock domain name
         get ONE generated signal, not two).
      3. a subsystem whose environment_manifest could not be resolved falls
         back to a synthesized `<protocol>_clk`/`<protocol>_rst_n` pair --
         a structural default (same shape as generator.py's own
         `m.get('clocks') or [{'name':'clk'}]` fallback), never a fabricated
         claim about a real signal name that was never actually observed.
    Only the FIRST declared clock/reset per subsystem is used, mirroring
    tb_top()'s own single-clock/single-reset-per-manifest simplification
    (`(m.get('clocks') or [...])[0]`)."""
    shared_clocks = manifest.get("shared_clocks")
    shared_resets = manifest.get("shared_resets")
    if shared_clocks or shared_resets:
        clocks = shared_clocks or [{"name": "clk"}]
        resets = shared_resets or [{"name": "rst_n"}]
        return clocks, resets

    clocks: List[Dict[str, str]] = []
    resets: List[Dict[str, str]] = []
    seen_c, seen_r = set(), set()
    for s in subsystems:
        proto = sv_id(s["name"])
        sub_m = _resolve_subsystem_manifest(s)
        c = (sub_m.get("clocks") or [{"name": f"{proto}_clk"}])[0]
        r = (sub_m.get("resets") or [{"name": f"{proto}_rst_n"}])[0]
        cname = sv_id(c.get("name", f"{proto}_clk"))
        rname = sv_id(r.get("name", f"{proto}_rst_n"))
        if cname not in seen_c:
            clocks.append({"name": cname})
            seen_c.add(cname)
        if rname not in seen_r:
            resets.append({"name": rname})
            seen_r.add(rname)
    return clocks or [{"name": "clk"}], resets or [{"name": "rst_n"}]


def _build_virtual_sequencer_fields(subsystems: List[Dict[str, Any]],
                                     manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Builds the "virtual_sequencer_fields" list UVMEnvironmentGenerator.vseq()
    already knows how to render (reused unchanged below -- see
    compose_soc_environment) -- one scalar field per registered subsystem,
    typed `<protocol>_virtual_sequencer` (the EXACT class name
    UVMEnvironmentGenerator.vseq() itself unconditionally emits for that
    subsystem: `class %s_virtual_sequencer extends uvm_sequencer #(...)`
    % p), named `<protocol>_vseqr`. This generalizes USB_UVM_Handoff's own
    real per-subsystem sub-sequencer field shape (usb_virtual_sequencer.sv
    line 36: `svt_apb_master_sequencer apb_seqr;`) to "whatever protocol is
    registered", exactly the genericity this module is scoped to.

    manifest["virtual_sequencer_fields"] is honored verbatim instead when
    present (same "explicit input wins" precedent as every other optional
    manifest key generator.py's own vseq()/env()/_connect_phase already
    support) -- a composition author who wants different field names/types
    is never overridden."""
    override = manifest.get("virtual_sequencer_fields")
    if override:
        return override
    fields = []
    for s in subsystems:
        proto = sv_id(s["name"])
        fields.append({
            "class_type": f"{proto}_virtual_sequencer",
            "field_name": f"{proto}_vseqr",
            "evidence": _cite(s) + (
                f" -- class '{proto}_virtual_sequencer' is the same name "
                "UVMEnvironmentGenerator.vseq() unconditionally emits for "
                "this subsystem's own virtual sequencer."
            ),
        })
    return fields


def _soc_tb_top(subsystems: List[Dict[str, Any]], manifest: Dict[str, Any]) -> str:
    """Emits soc_tb_top.sv following generator.py's OWN tb_top() pattern
    (see UVMEnvironmentGenerator.tb_top()), generalized from one subsystem
    to N: per-clock/per-reset `logic` declarations and toggling/deassert
    `initial` blocks (identical shape, just looped over
    _collect_clocks_resets()'s real per-subsystem clock/reset names instead
    of tb_top()'s single hardcoded pair), one `import <protocol>_env_pkg::*;`
    per registered subsystem, and one `<protocol>_env` handle per subsystem
    instantiated by name in an `initial` block -- `<protocol>_env` is the
    EXACT class name UVMEnvironmentGenerator.env() already emits for that
    subsystem (`class %s_env extends uvm_env` % p), so this instantiates a
    real already-generated class, never an invented one.

    Same honest limitation generator.py's own tb_top() already has (it emits
    a placeholder comment -- "// Bind DUT and VIP interfaces from
    environment_manifest.json/current evidence." -- rather than a fabricated
    interface bind): real cross-subsystem interface-level wiring
    (address_map/interrupt_map/dma_paths/connectivity entries in the
    composition manifest) is genuine system-topology content this generic
    composer does not synthesize either; it is surfaced as a comment listing
    what the manifest declares, not silently dropped."""
    clocks, resets = _collect_clocks_resets(subsystems, manifest)

    clk_decls = [f"  logic {sv_id(c.get('name', 'clk'))};" for c in clocks]
    rst_decls = [f"  logic {sv_id(r.get('name', 'rst_n'))};" for r in resets]
    clk_gens = [
        f"  initial begin {sv_id(c.get('name', 'clk'))}=0; "
        f"forever #5 {sv_id(c.get('name', 'clk'))}=~{sv_id(c.get('name', 'clk'))}; end"
        for c in clocks
    ]
    rst_gens = [
        f"  initial begin {sv_id(r.get('name', 'rst_n'))}=0; #100; "
        f"{sv_id(r.get('name', 'rst_n'))}=1; end"
        for r in resets
    ]

    imports = []
    env_decls = []
    env_creates = []
    for s in subsystems:
        proto = sv_id(s["name"])
        imports.append(f"  import {proto}_env_pkg::*;")
        env_decls.append(f"  {proto}_env {proto}_env_inst;")
        env_creates.append(
            f"    // evidence: {_cite(s)}\n"
            f'    {proto}_env_inst = {proto}_env::type_id::create("{proto}_env_inst", null);'
        )

    topology_keys = ("connectivity", "address_map", "interrupt_map", "dma_paths")
    topology_note = ""
    declared = [k for k in topology_keys if manifest.get(k)]
    if declared:
        topology_note = (
            "  // Composition manifest also declares: " + ", ".join(declared) + " --\n"
            "  // real cross-subsystem interface-level wiring from these is\n"
            "  // system-topology CONTENT this generic composer does not\n"
            "  // synthesize (see soc_environment_composer.py module\n"
            "  // docstring); bind it from current evidence, same honest\n"
            "  // limitation as generator.py's own tb_top()\n"
            "  // ('Bind DUT and VIP interfaces from environment_manifest.json\n"
            "  // /current evidence.').\n"
        )

    return (
        "module soc_tb_top;\n"
        "  import uvm_pkg::*;\n"
        + "\n".join(imports) + "\n"
        + "\n".join(clk_decls) + "\n"
        + "\n".join(rst_decls) + "\n"
        + "\n".join(clk_gens) + "\n"
        + "\n".join(rst_gens) + "\n"
        "  // Composed subsystem environments: each already-registered\n"
        "  // subsystem's real, already-generated top-level environment\n"
        "  // class, instantiated by name (SYSTEM_LEVEL_MODE composes\n"
        "  // already-built subsystem environments -- see CLAUDE.md\n"
        "  // 'Environment Generation Mode').\n"
        + "\n".join(env_decls) + "\n"
        "  initial begin\n"
        + "\n".join(env_creates) + "\n"
        "  end\n"
        + topology_note
        + "  initial run_test();\n"
        "endmodule\n"
    )


def cross_subsystem_scenarios(manifest: Dict[str, Any]) -> str:
    """STUB -- deliberately NOT implemented, per this module's docstring
    boundary. A cross-subsystem scenario (a virtual sequence that
    legitimately spans two-plus already-registered subsystems' own virtual
    sequencers, e.g. "USB bulk transfer concurrent with PCIe DMA traffic")
    is genuine protocol-BEHAVIOR content -- CLAUDE.md's "No Golden-Reference
    Content Mining" rule requires such content be sourced from PRIMARY
    evidence (VIP examples/user manual/source/class reference, or DUT
    RTL/PHY docs/programming guide) for the SPECIFIC subsystems involved.
    A subsystem_environment_registry entry carries only identity/
    qualification metadata, never sequence-body semantics, so a generic
    composer operating on registry entries alone has no primary source to
    draw this content from. Always raises -- never emits a plausible
    -looking placeholder sequence body."""
    raise NotImplementedError(
        "cross_subsystem_scenarios: genuinely protocol-specific content (a "
        "scenario spanning >=2 subsystems' own virtual sequences) that "
        "cannot be generated generically from subsystem_registry metadata "
        "alone -- requires primary per-subsystem VIP/DUT evidence for the "
        "specific subsystems being composed (CLAUDE.md 'No Golden-Reference "
        f"Content Mining'). manifest requested "
        f"{len(manifest.get('cross_subsystem_scenarios') or [])} "
        "cross_subsystem_scenarios entries; none can be honored generically."
    )


def end_to_end_scoreboard(manifest: Dict[str, Any]) -> str:
    """STUB -- deliberately NOT implemented; same boundary as
    cross_subsystem_scenarios() above. An end-to-end scoreboard that
    actually checks data/transactions crossing two-plus subsystems needs
    real knowledge of each subsystem's transaction item fields and the
    real transformation/routing between them (e.g. a DMA payload's byte
    order or address translation crossing a USB subsystem into a PCIe
    subsystem) -- protocol-BEHAVIOR content with no primary source in
    registry metadata. Always raises."""
    raise NotImplementedError(
        "end_to_end_scoreboard: genuinely protocol-specific checking logic "
        "(matching/comparing transactions across >=2 subsystems' own "
        "transaction item types) that cannot be generated generically from "
        "subsystem_registry metadata alone -- requires primary per-"
        "subsystem VIP/DUT evidence for the specific subsystems being "
        "composed (CLAUDE.md 'No Golden-Reference Content Mining'). "
        f"manifest requested "
        f"{len(manifest.get('end_to_end_scoreboards') or [])} "
        "end_to_end_scoreboards entries; none can be honored generically."
    )


def system_coverage(manifest: Dict[str, Any]) -> str:
    """STUB -- deliberately NOT implemented; same boundary as
    cross_subsystem_scenarios()/end_to_end_scoreboard() above. System-level
    coverage bins (e.g. "all subsystem pairs seen concurrently active",
    cross-subsystem interleaving bins) need real per-subsystem state/event
    semantics to define meaningful bins against -- protocol-BEHAVIOR
    content with no primary source in registry metadata. Always raises."""
    raise NotImplementedError(
        "system_coverage: genuinely protocol-specific coverage bin content "
        "(cross-subsystem interleaving/state coverage) that cannot be "
        "generated generically from subsystem_registry metadata alone -- "
        "requires primary per-subsystem VIP/DUT evidence for the specific "
        "subsystems being composed (CLAUDE.md 'No Golden-Reference Content "
        f"Mining'). manifest requested "
        f"{len(manifest.get('system_coverage') or [])} system_coverage "
        "entries; none can be honored generically."
    )


def cross_subsystem_findings(root: Any, subsystems: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The REAL SYS-9..SYS-14 cross-subsystem analysis for the subsystems this
    composition is about to compose, via
    `system_resource_inventory.real_cross_subsystem_findings()` -- the same
    function tools/verification_flow/system_level_composition_gate.py and
    system_level_resource_contention_gate.py cross-check against, so the gate
    that admits a composition and the composer that performs it are reading
    ONE analysis, not two.

    Imported lazily: this package is imported by generation paths that have no
    business pulling in the whole SYS-1..SYS-14 stack, and a composition
    called without a `root` (every pre-2026-09-05 caller, and every unit
    fixture) must stay unaffected."""
    from ..system_resource_inventory import real_cross_subsystem_findings
    return real_cross_subsystem_findings(root, [s["name"] for s in subsystems])


def compose_soc_environment(subsystem_registry_entries: List[Dict[str, Any]],
                             manifest: Dict[str, Any],
                             root: Any = None) -> Dict[str, str]:
    """Composes a Full-SoC/System-Level testbench scaffold from N already
    -registered subsystem environments. Same return shape as
    UVMEnvironmentGenerator.generate(): dict[filename -> generated SV/JSON
    content], caller writes it to disk (see dv_harness/engine.py's
    _compose_soc_environment_files() for the real SIGNOFF-adjacent call
    site -- SYSTEM_LEVEL stage's system_level_validator gate PASS).

    Args:
      subsystem_registry_entries: real
        .dv-harness/soc-composer/subsystem_environment_registry.json
        "subsystems" entries (or structurally-equivalent test fixtures) --
        each item is trusted to already carry a real "name"; the fuller
        required-field set is subsystem_environment_registration_gate.py's
        job to enforce BEFORE an entry is ever persisted (see
        MissingSubsystemNameEvidenceError docstring for the RULING on why
        this function does not re-enforce that whole set).
      manifest: the SoC composition manifest (soc_composition_manifest_
        template.json schema: soc_name, shared_clocks, shared_resets,
        cross_subsystem_scenarios, end_to_end_scoreboards, system_coverage,
        optional virtual_sequencer_fields override, ...). Every key is
        optional and additive -- an empty {} degrades to structural
        defaults exactly like generator.py's own manifest handling.
      root: the real project root, when one exists. Supplying it runs the
        REAL cross-subsystem analysis over these subsystems before composing
        (see cross_subsystem_findings() and
        CrossSubsystemIntegrationBlockedError) and records the result in
        soc_composition_manifest.json's "cross_subsystem_analysis". None
        skips the consultation and composes exactly as before.

    Returns three files on the fully-generic, always-honorable path:
      - soc_tb_top.sv: see _soc_tb_top().
      - soc_virtual_sequencer.sv: UVMEnvironmentGenerator.vseq() reused
        UNCHANGED (not reimplemented -- literally the same function,
        called unbound since vseq() never touches `self`) against a
        virtual_sequencer_fields list built by
        _build_virtual_sequencer_fields() -- "don't invent new schema".
      - soc_composition_manifest.json: audit-trail record (composed
        subsystem names + generated file list), same bookkeeping shape as
        generate()'s own environment_manifest.json.

    Raises EmptySubsystemRegistryError / MissingSubsystemNameEvidenceError
    for structurally invalid input, CrossSubsystemIntegrationBlockedError
    when `root` is supplied and the real analysis found an unresolved
    active-driver ownership conflict, or propagates NotImplementedError from
    cross_subsystem_scenarios()/end_to_end_scoreboard()/system_coverage()
    when manifest explicitly requests content in those genuinely
    protocol-specific categories (manifest keys of the same name,
    non-empty) -- same additive/no-op-when-absent convention as every
    other optional generator.py manifest key: a manifest that never asks
    for that content is unaffected and this function returns normally."""
    if not subsystem_registry_entries:
        raise EmptySubsystemRegistryError("EMPTY_SUBSYSTEM_REGISTRY", {
            "subsystem_registry_entries": subsystem_registry_entries,
        })

    subsystems = []
    for i, entry in enumerate(subsystem_registry_entries):
        if not isinstance(entry, dict) or not entry.get("name"):
            raise MissingSubsystemNameEvidenceError("MISSING_SUBSYSTEM_NAME_EVIDENCE", {
                "index": i, "entry": entry,
            })
        subsystems.append(entry)

    # Consult the REAL cross-subsystem analysis BEFORE composing anything, so
    # a refusal leaves no half-written environment behind. `root=None` (every
    # caller before 2026-09-05, and every unit fixture that has no project on
    # disk) skips it and composes exactly as before; both real call sites --
    # engine.py's _compose_soc_environment_files() and create_environment.py's
    # SYSTEM_LEVEL_MODE dispatch -- now pass their real project root.
    findings: Dict[str, Any] = {}
    if root is not None:
        findings = cross_subsystem_findings(root, subsystems)
        if (findings.get("status") == "TRACK_B_ANALYSIS_AVAILABLE"
                and not findings.get("automatic_integration_allowed")):
            raise CrossSubsystemIntegrationBlockedError(
                "CROSS_SUBSYSTEM_INTEGRATION_BLOCKED", {
                    "subsystems": findings["subsystems"],
                    "driver_conflicts": findings["driver_conflicts"],
                    "stopped_resource_ids": findings["stopped_resource_ids"],
                    "held_resource_ids": findings["held_resource_ids"],
                    "blocking_decisions": findings["blocking_decisions"],
                    "human_arbitration_required": True,
                    "preferred_model": findings["preferred_model"],
                })

    files: Dict[str, str] = {}

    # (2) soc_virtual_sequencer.sv -- reuses UVMEnvironmentGenerator.vseq()
    # verbatim (it never references `self`, so an unbound call with no real
    # instance is safe and avoids UVMEnvironmentGenerator.__init__'s
    # out_dir-mkdir side effect, which this composer -- like generate()'s
    # own caller -- does not want triggered as a side effect of building
    # file CONTENT before the caller has decided where/whether to write it).
    vseqr_manifest = {"virtual_sequencer_fields": _build_virtual_sequencer_fields(subsystems, manifest)}
    files["soc_virtual_sequencer.sv"] = UVMEnvironmentGenerator.vseq(None, vseqr_manifest, "soc")

    # (1) soc_tb_top.sv
    files["soc_tb_top.sv"] = _soc_tb_top(subsystems, manifest)

    # (3) genuinely protocol-specific content -- explicit, honest
    # NotImplementedError boundary. Only triggered when the manifest asks
    # for it (non-empty list), same additive-when-absent convention as
    # every other optional manifest key in this codebase; a composition
    # that never asks for cross-subsystem scenario/scoreboard/coverage
    # content composes successfully and returns normally.
    if manifest.get("cross_subsystem_scenarios"):
        cross_subsystem_scenarios(manifest)
    if manifest.get("end_to_end_scoreboards"):
        end_to_end_scoreboard(manifest)
    if manifest.get("system_coverage"):
        system_coverage(manifest)

    composed = dict(manifest)
    composed["composed_subsystems"] = [s["name"] for s in subsystems]
    # The composition is no longer blind to cross-subsystem findings: what the
    # real analysis said (including an explicit TRACK_B_ANALYSIS_UNAVAILABLE
    # with its reason, or "NOT_CONSULTED" when no root was supplied) is part
    # of the composition's own audit record.
    composed["cross_subsystem_analysis"] = (
        findings if findings else {"status": "NOT_CONSULTED",
                                   "reason": "NO_PROJECT_ROOT_SUPPLIED"})
    composed["generated_files"] = sorted(files.keys()) + ["soc_composition_manifest.json"]
    composed["composition_status"] = "SOC_TB_COMPOSED"
    files["soc_composition_manifest.json"] = json.dumps(composed, indent=2)

    return files
