"""dv_harness/uvm_generator/bind_mechanism_generator.py -- real DV_UVM
two-hook bridge/bind skeleton generator, matching CORE/ip-uvm-dv-gen/SKILL.md's
actual enforced convention (confirmed against a real project, not
aspirational): Hook 1 (`` `ifdef DV_UVM `` swap in DUT/MODEL/<model>.v,
including `dv_uvm_hook.svh` instead of `command.txt`) and Hook 2 (one
appended filelist line in DUT/vcs.opt). Everything besides the macro
redirect / bridge instances / pattern `initial` block -- which must live at
TOP-MODULE SCOPE per that SKILL.md's own table -- is wired via `bind`,
targeted at wherever the signal is actually declared in the DUT hierarchy,
never assumed to be at the subsystem boundary.

BUG FIX (2026-08-29, 9-policy audit / USB regen-fidelity plan Phase 1 item
3): this generator refuses to fabricate a bind target, port list, or reason
-- every bind entry must come from currently-supplied evidence
(`bind_entries`), never invented. A bind entry missing its `reason` (why
THIS instance/signal was chosen -- e.g. "irq_evt_reg declared at
chip.core.evt_ctrl; the subsystem wrapper only routes it through, not owns
it") or an empty `ports` list is a hard BindTopologyError, never a silently
emitted empty bind -- the same evidence discipline
AMBAFabricGenerator's scoreboard-matrix rule already established for this
session's other new generators.

GAP CLOSE (2026-09-06, self_check_list.md #27 / uvm_bridge_task_verification,
audit-first): a full read of this module plus the one real generated example
this repo ships (`examples/generated_usb_real_evidence_v1/bind/
dv_uvm_hook.svh`) confirmed `emit_hook_svh()`'s `top_scope_decls` parameter
had never actually been populated with a real bridge task body anywhere in
this codebase -- the shipped example's own bridge-instance section is a bare
`TODO_PLACEHOLDER` comment, not raw pin-level bridging and not APB-sequence-
calling bridging, just nothing. `ApbBridgeTaskError` /
`validate_apb_bridge_entries()` / `emit_apb_bridge_tasks_sv()` below close
that: real, evidence-gated CPUREAD/CPUWRITE task bodies that call a real UVM
APB sequence item (`uvm_create_on` / `randomize() with` / `execute_item()`),
never a raw force/deposit and never a fabricated VIP field/class name.
"""
from __future__ import annotations


class BindTopologyError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def assert_phy_boundary_decided_first(bind_entries, phy_boundary_doc,
                                       *, require_phy_boundary: bool = False):
    """The MOUNT-LAYER gate, run BEFORE the bind-confidence tier gate.

    CLAUDE.md Bind-Location Rule 5 states the ordering this function is: the
    PHY model's existence and type decides WHICH LAYER a monitor may be
    mounted at; only after that layer is fixed does locating the hierarchy
    path inside it become a question at all. Choosing a target path first
    and asking afterwards whether a PHY sits in between is the backwards
    order, and it is not a harmless reordering -- it is how a bind lands on
    line-rate serial lanes. Such a bind elaborates (Gate 1 PASS), sees a
    toggling clock and a released reset (Gate 2 PASS), and only fails at
    Gate 3, as a monitor that decoded nothing. `connectivity.py`'s tier
    classifier cannot catch that: a serial-lane target can be a perfectly
    good T1 structural match. Layer-correctness and path-correctness are
    independent, so they need independent gates.

    `phy_boundary_doc` is a real `dv_harness.phy_boundary` document
    (`extract_phy_boundary()` / `load_phy_boundary()`), never a hand-written
    dict -- its `bind_decision` carries the port widths it was computed
    from. Refusal is `phy_boundary.PhyBoundaryValidationError`, propagated
    unwrapped exactly as `BindTierError` is from the tier gate, so a caller
    sees which of the two independent gates refused.

    An entry may declare the boundary signals it actually connects through
    as `phy_boundary_signals`; when it does, those are checked against the
    sanctioned parallel port set as well. That is what refuses the specific
    case of binding the SERIAL lanes of a MIXED boundary -- a boundary whose
    document says `bindable: true`, so the mount-layer check alone passes it.

    `require_phy_boundary=True` makes an ABSENT document a hard refusal:
    that is the strict reading of the ordering rule (no bind may be emitted
    before the layer decision exists). It defaults False so the existing
    3-field entry contract, and every caller that has no PHY in scope at all
    (an IP-level DUT with no PHY sub-block), keeps working unchanged."""
    if phy_boundary_doc is None:
        if require_phy_boundary:
            raise BindTopologyError(
                "PHY_BOUNDARY_NOT_DECIDED",
                {"detail": "require_phy_boundary=True but no phy_boundary document was supplied; "
                           "run dv_harness.phy_boundary.extract_phy_boundary() and decide the "
                           "mount layer BEFORE choosing a bind target (CLAUDE.md Bind-Location "
                           "Rule 5)"})
        return None
    # Local import, same convention as the tier gate below: keeps this
    # generator importable without pulling in phy_boundary's jsonschema
    # dependency surface at module-import time.
    from ..phy_boundary import assert_bind_location_allowed

    decision = assert_bind_location_allowed(phy_boundary_doc)
    for entry in bind_entries or []:
        declared = entry.get("phy_boundary_signals")
        if declared:
            assert_bind_location_allowed(phy_boundary_doc, target_signals=declared)
    return decision


def validate_bind_entries(bind_entries, *, require_tier: bool = False,
                          phy_boundary_doc=None, require_phy_boundary: bool = False):
    """Evidence check for every bind entry, then the MOUNT-LAYER gate, then
    the bind-confidence TIER gate -- in that order, which is itself the rule
    (see `assert_phy_boundary_decided_first`).

    The tier gate is `connectivity.enforce_bind_tier_policy()` -- the
    downstream consumer `connectivity.assert_t3_never_auto_accepted()` was
    written for. Before it was wired here, this generator would emit a
    `bind` statement for an entry the pipeline had already classified as
    naming-heuristic-only (T3, "ALWAYS requires human confirmation") or as
    undecidable (T4, belongs in the question queue), with no check at all.

    `require_tier=False` keeps the existing 3-field entry contract
    (`target_instance`/`ports`/`reason`) working for callers that do not yet
    classify tiers; pass True to additionally require every entry carry one."""
    if not bind_entries:
        raise BindTopologyError("NO_BIND_ENTRIES", {})
    for i, entry in enumerate(bind_entries):
        target = entry.get("target_instance")
        if not target:
            raise BindTopologyError("MISSING_BIND_EVIDENCE", {"index": i, "field": "target_instance"})
        if not entry.get("ports"):
            raise BindTopologyError("MISSING_BIND_EVIDENCE",
                                     {"index": i, "target_instance": target, "field": "ports"})
        if not entry.get("reason"):
            raise BindTopologyError("MISSING_BIND_EVIDENCE",
                                     {"index": i, "target_instance": target, "field": "reason"})
    # Mount layer BEFORE hierarchy path: a serial-lane bind can be a clean
    # T1 structural match, so running the tier gate first would pass it.
    assert_phy_boundary_decided_first(
        bind_entries, phy_boundary_doc, require_phy_boundary=require_phy_boundary)
    # Local import: keeps this generator importable without pulling in
    # connectivity's own dependency surface at module-import time, matching
    # connectivity.build_t4_question_queue_entry()'s own convention.
    from ..connectivity import enforce_bind_tier_policy
    enforce_bind_tier_policy(bind_entries, require_tier=require_tier)
    return bind_entries


def emit_bind_sv(bind_entries, *, require_tier: bool = False,
                 phy_boundary_doc=None, require_phy_boundary: bool = False) -> str:
    """Pure textual `bind` statement assembly from input evidence only --
    never invents a signal/module name not present in `bind_entries`, never
    mounts at a layer the PHY boundary says is not bindable, and never emits
    an unconfirmed T3 or any T4 entry (see `validate_bind_entries`)."""
    validate_bind_entries(bind_entries, require_tier=require_tier,
                          phy_boundary_doc=phy_boundary_doc,
                          require_phy_boundary=require_phy_boundary)
    lines = [
        "// GENERATED by dv_harness/uvm_generator/bind_mechanism_generator.py --",
        "// every bind target below is evidence-supplied (bind_entries), never invented.",
        "// Convention: CORE/ip-uvm-dv-gen/SKILL.md -- bind targeted at where the signal",
        "// is actually declared in the DUT hierarchy, not assumed at the subsystem boundary.",
        "",
    ]
    for entry in bind_entries:
        target = entry["target_instance"]
        bind_module = entry.get("bind_module", "dv_uvm_probe")
        inst_name = entry.get("inst_name", f"u_{target.split('.')[-1]}_probe")
        port_conns = ", ".join(f".{p}({p})" for p in entry["ports"])
        lines.append(f"// {entry['reason']}")
        lines.append(f"bind {target} {bind_module} {inst_name} ({port_conns});")
    return "\n".join(lines) + "\n"


class ApbBridgeTaskError(ValueError):
    """Raised by validate_apb_bridge_entries()/emit_apb_bridge_tasks_sv() when a
    proposed CPUREAD/CPUWRITE bridge task entry is missing required evidence.
    Same typed-error convention as BindTopologyError above: never a silently
    emitted task body -- every VIP sequencer path, transaction class, and
    field name must come from currently-supplied evidence (`bridge_entries`),
    never invented.

    2026-09-06 audit finding (self_check_list.md #27, uvm_bridge_task_verification):
    the two-hook bridge skeleton this module emits (`emit_hook_svh`) leaves
    the actual bridge task body -- what a hook redirect like
    `` `define CPUWRITE1B dv_uvm_cpuwrite1b `` resolves INTO -- entirely to a
    caller-supplied `top_scope_decls` string. Every real generated example
    this repo ships (`examples/generated_usb_real_evidence_v1/bind/
    dv_uvm_hook.svh`) carries only a literal `TODO_PLACEHOLDER` comment there:
    no bridge task body -- real APB-sequence-calling or even raw pin-level --
    had ever actually been generated. `emit_apb_bridge_tasks_sv()` below is
    that missing piece: an additive generator function producing real task
    bodies that call a real UVM APB sequence item (`uvm_create_on` /
    `randomize() with` against caller-cited real VIP transaction fields /
    the standard UVM `execute_item()` sequencer API), evidence-gated exactly
    like `emit_bind_sv()` above. It does not replace a project's own richer
    arbiter-plus-persistent-sequence bridge design (the real
    `USB_UVM_Handoff/uvm/tb/seq/usb_apb_bridge_seq.sv` +
    `uvm/tb/top/usb_apb_arb.sv` pattern, kept as hand-authored/project-
    specific evidence, per "No Golden-Reference Content Mining") -- this is
    the minimal generic default so a generated environment's own bridge
    tasks are never left doing nothing at all behind a bare placeholder
    comment."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


APB_BRIDGE_DIRECTIONS = ("WRITE", "READ")


def validate_apb_bridge_entries(bridge_entries):
    """Evidence check for every CPUREAD/CPUWRITE bridge task entry, mirroring
    validate_bind_entries()'s discipline: every field that ends up in
    generated SystemVerilog (the VIP sequencer path, the VIP transaction
    class, its address/data field names) must be evidence-supplied, never
    guessed from a naming convention."""
    if not bridge_entries:
        raise ApbBridgeTaskError("NO_BRIDGE_ENTRIES", {})
    required = ("task_name", "direction", "sequencer_path",
                "vip_transaction_type", "vip_addr_field", "vip_data_field",
                "addr_width", "data_width", "reason")
    seen_task_names = set()
    for i, entry in enumerate(bridge_entries):
        for field in required:
            value = entry.get(field)
            if value in (None, "") or (isinstance(value, (list, dict)) and not value):
                raise ApbBridgeTaskError(
                    "MISSING_BRIDGE_EVIDENCE",
                    {"index": i, "task_name": entry.get("task_name"), "field": field})
        if entry["direction"] not in APB_BRIDGE_DIRECTIONS:
            raise ApbBridgeTaskError(
                "INVALID_BRIDGE_DIRECTION",
                {"index": i, "task_name": entry["task_name"],
                 "direction": entry.get("direction"),
                 "allowed": list(APB_BRIDGE_DIRECTIONS)})
        task_name = entry["task_name"]
        if task_name in seen_task_names:
            raise ApbBridgeTaskError(
                "DUPLICATE_BRIDGE_TASK_NAME", {"index": i, "task_name": task_name})
        seen_task_names.add(task_name)
        # If a VIP transaction-kind field is cited at all, the enum value for
        # THIS entry's own direction must be cited too -- a WRITE entry
        # citing vip_xact_type_field but no vip_write_enum would otherwise
        # silently drop the constraint that makes the emitted transaction a
        # write rather than whatever the field's default happens to be.
        xtype_field = entry.get("vip_xact_type_field")
        if xtype_field:
            enum_key = "vip_write_enum" if entry["direction"] == "WRITE" else "vip_read_enum"
            if not entry.get(enum_key):
                raise ApbBridgeTaskError(
                    "MISSING_BRIDGE_EVIDENCE",
                    {"index": i, "task_name": task_name, "field": enum_key})
    return bridge_entries


def emit_apb_bridge_tasks_sv(bridge_entries) -> str:
    """Pure textual bridge-task assembly from input evidence only -- never
    invents a VIP sequencer path, transaction class, or field name not
    present in `bridge_entries`. Each emitted task is what a
    `` `define CPUWRITE1B dv_uvm_cpuwrite1b `` (or CPUREAD*) hook redirect
    from emit_hook_svh() actually resolves to: a real UVM sequence item
    created against the caller-cited VIP sequencer (`uvm_create_on`),
    randomized against caller-cited real VIP transaction fields, and
    executed via the standard UVM `execute_item()` sequencer API -- never a
    raw pin-level force/deposit and never a fabricated VIP API. Intended as
    the content of one `top_scope_decls` entry passed to `emit_hook_svh()`,
    closing the confirmed gap where the generated example's own bridge-
    instance section was a bare TODO_PLACEHOLDER
    (self_check_list.md #27, audited 2026-09-06)."""
    validate_apb_bridge_entries(bridge_entries)
    lines = [
        "// GENERATED by dv_harness/uvm_generator/bind_mechanism_generator.py --",
        "// every VIP sequencer path / transaction class / field name below is",
        "// evidence-supplied (bridge_entries), never invented. Each task below IS",
        "// the real bridge a CPUREAD/CPUWRITE hook redirect (emit_hook_svh) points",
        "// at: it creates and executes a real UVM sequence item against a real VIP",
        "// sequencer, never a raw pin-level force/deposit.",
    ]
    for entry in bridge_entries:
        task_name = entry["task_name"]
        seqr = entry["sequencer_path"]
        xact_type = entry["vip_transaction_type"]
        addr_field = entry["vip_addr_field"]
        data_field = entry["vip_data_field"]
        addr_w = entry["addr_width"]
        data_w = entry["data_width"]
        is_write = entry["direction"] == "WRITE"

        constraints = [f"{addr_field} == addr;"]
        xtype_field = entry.get("vip_xact_type_field")
        if xtype_field:
            enum_val = entry["vip_write_enum"] if is_write else entry["vip_read_enum"]
            constraints.insert(0, f"{xtype_field} == {enum_val};")
        if is_write:
            constraints.append(f"{data_field} == data;")
        constraint_block = "\n      ".join(constraints)

        lines.append("")
        lines.append(f"// {entry['reason']}")
        if is_write:
            lines.append(f"task {task_name}(input bit [{addr_w - 1}:0] addr, "
                          f"input bit [{data_w - 1}:0] data);")
        else:
            lines.append(f"task {task_name}(input bit [{addr_w - 1}:0] addr, "
                          f"output bit [{data_w - 1}:0] data);")
        lines.append(f"  {xact_type} req;")
        lines.append(f"  `uvm_create_on(req, {seqr})")
        lines.append("  if (!req.randomize() with {")
        lines.append(f"      {constraint_block}")
        lines.append(f"  }}) `uvm_fatal(\"{task_name}\", \"randomization failed\")")
        lines.append(f"  {seqr}.execute_item(req);")
        if not is_write:
            lines.append(f"  data = req.{data_field};")
        lines.append("endtask")
    return "\n".join(lines) + "\n"


def emit_hook_svh(protocol: str, macro_redirects: dict, top_scope_decls) -> str:
    """The `` `ifdef DV_UVM ``/dual-hook skeleton per CORE/ip-uvm-dv-gen/
    SKILL.md's "two hooks" rule, with the preprocessing-order comment and the
    top-module-scope rationale emitted literally (macro redirect / bridge
    instances / pattern initial block cannot be `bind`-ed)."""
    redirects = "\n".join(f"`define {old} {new}" for old, new in macro_redirects.items())
    decls = "\n".join(f"  {d}" for d in top_scope_decls)
    return f"""// GENERATED by dv_harness/uvm_generator/bind_mechanism_generator.py --
// dv_uvm_hook.svh for protocol '{protocol}'. Included from DUT/MODEL/<model>.v's
// Hook 1 (`` `ifdef DV_UVM ``); everything here runs at TOP-MODULE SCOPE
// because it cannot be `bind`-ed (CORE/ip-uvm-dv-gen/SKILL.md "What must be
// at top-module scope" table): the macro redirect (preprocessing is
// sequential -- placed before the model's task definitions so every
// register access inside those tasks is redirected with no edit to any of
// them), the bridge instances (patterns reach them by hierarchical path),
// and the pattern `initial` block (declares the variables patterns use,
// under the original names).

// -- macro redirect (must precede the model's task definitions) --
{redirects}

// -- bridge instances + pattern initial block (top-module scope) --
{decls}

initial run_test();
"""
