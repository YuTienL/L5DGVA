# NOTICE (added during industrial-grade audit, 2026-08-28): this module is
# NOT invoked by any executing code path in dv_harness/ or .claude/agents/*.md
# as of this audit -- it is standalone/orphaned code. Any WORKFLOW_MANIFEST.json
# capability flag referencing this file's feature is aspirational, not a
# statement that this code actually runs in the pipeline. See
# CHANGELOG_v0_to_v50.md and the industrial-grade-deep-audit findings for detail.
from pathlib import Path
import json, re
from ..qualification import QualificationTier

def sv_id(s):
    s=re.sub(r'[^A-Za-z0-9_]', '_', str(s))
    if not s or s[0].isdigit():
        s='p_'+s
    return s.lower()


class CircularDependencyError(ValueError):
    """Raised by topological_build_order when vip_components' depends_on
    graph has a cycle. Follows the AddressMapError/ScoreboardMatrixError
    typed-error convention from amba_fabric_generator.py: a short
    SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict --
    never a silently-picked arbitrary order for an unsatisfiable graph."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class UnknownDependencyError(ValueError):
    """Raised by topological_build_order when a depends_on entry names a
    component not present in the vip_components list -- never silently
    ignored."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class MissingConnectionEvidenceError(ValueError):
    """Raised by UVMEnvironmentGenerator._connect_phase when a top-level
    "connections" manifest entry has no non-empty "evidence" string. Same
    typed-error convention as CircularDependencyError/UnknownDependencyError/
    InvalidPortCountError above: a short SCREAMING_SNAKE_CASE `reason` code
    plus a concrete `detail` dict -- a connect_phase wire-up is never
    silently accepted without a citation of where it came from (real
    evidence: USB_UVM_Handoff's usb_top_env.sv connect_phase, e.g. line 472,
    `if (apb_env != null) virt_seqr.apb_seqr = apb_env.master.sequencer;` --
    every such assignment in this generator's output must be traceable back
    to a real line like that one)."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class MissingVirtualSequencerFieldEvidenceError(ValueError):
    """Raised by UVMEnvironmentGenerator.vseq when a top-level
    "virtual_sequencer_fields" manifest entry has no non-empty "evidence"
    string. Same typed-error convention as CircularDependencyError/
    UnknownDependencyError/MissingConnectionEvidenceError/InvalidPortCountError
    above: a short SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail`
    dict -- a virtual-sequencer field declaration is never silently accepted
    without a citation of where it came from (real evidence:
    USB_UVM_Handoff's usb_virtual_sequencer.sv, e.g. line 36,
    `svt_apb_master_sequencer apb_seqr;`, and line 21,
    `svt_usb_transfer_sequencer usb_xfer_seqr[2];` -- every declared field in
    this generator's output must be traceable back to a real line like
    those)."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class MissingSequenceBodyEvidenceError(ValueError):
    """Raised by UVMEnvironmentGenerator.base_vseq when a top-level
    "virtual_sequences" manifest entry has no non-empty "evidence" string.
    Same typed-error convention as MissingConnectionEvidenceError/
    MissingVirtualSequencerFieldEvidenceError above: a short
    SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict -- a
    generated virtual-sequence body is never accepted without a citation of
    the real VIP example/class it was modeled on (real evidence: the VIP
    example D:/DV/Task/USB/VIP/examples/tb_usb_svt_uvm_20_phy/env/
    usb_directed_transfers_sequence.sv, lines 157-325's
    `uvm_create`+fix_anchors+`randomize() with{}`+`uvm_send` idiom, and
    usb_isoc_sequence.sv's `uvm_do_with` idiom -- every "virtual_sequences"
    entry emitted by this generator must be traceable back to a citation
    like one of those)."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class MalformedSequenceFieldValueError(ValueError):
    """Raised by UVMEnvironmentGenerator._emit_virtual_sequence when a
    "steps[].field_values" list entry is not a {"field": <non-empty str>,
    "value": <present>} dict -- same typed-error convention as this module's
    other errors. A `field == value;` constraint line is never emitted from
    a malformed/guessed entry."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class MalformedScoreboardCheckError(ValueError):
    """Raised by UVMEnvironmentGenerator._emit_scoreboard_check when a
    top-level "scoreboard_rules" entry opts into the structured
    SCOREBOARD_CHECKS DSL (identified, per scoreboard()'s own docstring, by
    the presence of a "check_name" key) but is missing/malformed in any of:
    "lhs_source"/"rhs_source" (each requiring non-empty "component" and
    "field"), "compare_op" (must be one of eq|neq|lt|lte|gt|gte|mask_eq),
    "on_mismatch" (requiring "severity" in UVM_ERROR|UVM_WARNING|UVM_INFO and
    a non-empty "message_template"), a "register_decode" with a non-negative
    int "bit_offset" and positive int "bit_width", an "enum_translation"
    whose "kind" is anything other than the one currently-supported
    "value_map" or whose "map" is missing/empty or whose "note" is empty (the
    evidence-discipline requirement: a real design pass -- see this task's
    DSL spec, the USB EPTYPE/enum_translation case -- must always cite why a
    cross-domain value mapping is correct, even an identity one, never leave
    it un-cited), or compare_op "mask_eq" with no top-level "mask" string.
    Same typed-error convention as this module's other errors: a short
    SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict -- a
    structured scoreboard check is never silently compiled from a
    guessed/incomplete entry, and never silently falls back to the legacy
    comment-dump path once it has opted in via "check_name"."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class ConstructionCollisionError(ValueError):
    """Raised by UVMEnvironmentGenerator._env_multi_component when a top-level
    "connections" entry with kind="construct" targets the same real object
    (matched by instance_name, array-index suffix on "lhs" stripped, e.g.
    "payload_cb[{p}]" -> "payload_cb") as a vip_components entry whose kind
    is NOT "plain_object". Same typed-error convention as
    CircularDependencyError/UnknownDependencyError/InvalidPortCountError
    above: a short SCREAMING_SNAKE_CASE `reason` code plus a concrete
    `detail` dict.

    This is the same shape of problem the pre-existing cfg/vseqr/sb/cov
    reserved-name mechanism in _env_multi_component already handles for its
    own boilerplate fields (two schema paths independently deciding to
    construct the same real object) -- but for a factory-created
    (::type_id::create()) or interface (config_db get()) component, silently
    dropping the build_phase construction the way the plain_object dedup does
    would be wrong: it is the ONLY construction site for that object, unlike
    payload_cb, which real evidence (USB_UVM_Handoff's usb_top_env.sv:85/506)
    shows is declared but never built in build_phase at all, only in
    connect_phase. A manifest that puts a "construct" connections entry
    against a class-handle or interface component most likely did not
    realize the collision (there is no real-evidence case of this
    combination), so this error surfaces it rather than either silently
    double-constructing the object or silently discarding a real
    ::type_id::create()/config_db get()."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class InvalidPortCountError(ValueError):
    """Raised by UVMEnvironmentGenerator._env_multi_component when a
    vip_components entry sets "port_indexed": true but the manifest has no
    valid top-level "port_count" (positive int). Same typed-error convention
    as CircularDependencyError/UnknownDependencyError above: a short
    SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict -- never
    a silently-guessed port count (real evidence: USB_UVM_Handoff's
    usb_top_env.sv declares its per-port arrays sized by a real, explicit
    NUM_USB_PORTS parameter, e.g. `svt_usb_agent usb_host_agent[NUM_USB_PORTS];`
    at line 77 -- there is no protocol-general default to fall back to)."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def topological_build_order(components: list) -> list:
    """Pure function: given a vip_components-shaped list of
    {"name", "class_type", "instance_name", "depends_on": [...]} dicts,
    return the component `name`s in a valid build order satisfying every
    depends_on constraint (Kahn's algorithm). Ties (components with no
    remaining unresolved dependencies at the same point) are broken by
    input-list order, so a flat list with no depends_on at all degenerates
    to input order exactly -- no ordering is claimed beyond what the
    manifest actually asserted (CLAUDE.md Evidence Truth Rule applied to
    generation time).

    Raises UnknownDependencyError if a depends_on entry names a component
    not present in `components`. Raises CircularDependencyError if the
    depends_on graph has a cycle.
    """
    names = [c["name"] for c in components]
    name_set = set(names)
    depends_on = {c["name"]: list(c.get("depends_on") or []) for c in components}

    for name in names:
        for dep in depends_on[name]:
            if dep not in name_set:
                raise UnknownDependencyError("UNKNOWN_DEPENDENCY", {
                    "component": name, "unknown_dependency": dep,
                    "known_components": names,
                })

    in_degree = {name: len(depends_on[name]) for name in names}
    dependents = {name: [] for name in names}
    for name in names:
        for dep in depends_on[name]:
            dependents[dep].append(name)

    queue = [name for name in names if in_degree[name] == 0]
    order = []
    i = 0
    while i < len(queue):
        cur = queue[i]
        i += 1
        order.append(cur)
        for nxt in dependents[cur]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(names):
        remaining = [n for n in names if n not in order]
        raise CircularDependencyError("CIRCULAR_DEPENDENCY", {
            "remaining_components": remaining, "components": names,
        })
    return order


class UVMEnvironmentGenerator:
    def __init__(self,out_dir):
        self.out=Path(out_dir)
        self.out.mkdir(parents=True,exist_ok=True)

    def generate(self,m):
        p=sv_id(m['protocol'])
        pkg=p+'_env_pkg'
        smoke=m.get('smoke_tests') or [{'name':'smoke'}]
        files={}
        files[pkg+'.sv']=self.pkg(m,p,pkg,smoke)
        files[p+'_config.sv']=self.config(m,p)
        files[p+'_virtual_sequencer.sv']=self.vseq(m,p)
        files[p+'_base_vseq.sv']=self.base_vseq(m,p)
        files[p+'_scoreboard.sv']=self.scoreboard(m,p)
        files[p+'_coverage.sv']=self.coverage(m,p)
        files[p+'_env.sv']=self.env(m,p)
        files[p+'_base_test.sv']=self.base_test(m,p)
        for t in smoke:
            n=sv_id(t.get('name','smoke'))
            files[p+'_'+n+'_test.sv']=self.smoke_test(m,p,n)
        files['tb_top.sv']=self.tb_top(m,p,pkg)
        files['filelist.f']=pkg+'.sv\ntb_top.sv\n'
        manifest=dict(m)
        manifest['generated_files']=list(files.keys())
        manifest['qualification_status']=QualificationTier.ENV_GENERATED.value
        files['environment_manifest.json']=json.dumps(manifest,indent=2)
        for n,c in files.items():
            (self.out/n).write_text(c,encoding='utf-8')
        return list(files.keys())

    def pkg(self,m,p,pkg,smoke):
        imports='\n'.join('  import '+x+'::*;' for x in m.get('vip',{}).get('package_imports',[]))
        incs=[p+'_config.sv',p+'_virtual_sequencer.sv',p+'_base_vseq.sv',
              p+'_scoreboard.sv',p+'_coverage.sv',p+'_env.sv',p+'_base_test.sv']
        incs += [p+'_'+sv_id(t.get('name','smoke'))+'_test.sv' for t in smoke]
        inc='\n'.join('  `include "'+x+'"' for x in incs)
        return 'package '+pkg+';\n  import uvm_pkg::*;\n  `include "uvm_macros.svh"\n'+imports+'\n'+inc+'\nendpackage\n'

    def config(self,m,p):
        return '''class %s_config extends uvm_object;
  `uvm_object_utils(%s_config)
  bit is_active = 1'b1;
  string role = "%s";
  function new(string name="%s_config"); super.new(name); endfunction
endclass
''' % (p,p,m.get('role','UNKNOWN'),p)

    def vseq(self,m,p):
        """VIRTUAL_SEQUENCER_FIELDS EXTENSION (additive, backward compatible
        -- a manifest with no top-level "virtual_sequencer_fields" key, or an
        empty list, is a complete no-op here: the generic numbered
        `uvm_sequencer_base seqr_%d;` handle path below runs exactly as
        before, byte-identical output).

        Real evidence is USB_UVM_Handoff's usb_virtual_sequencer.sv, which
        never declares generic numbered `seqr_N` handles at all -- it
        declares real, protocol-specific typed fields:
          line 21: svt_usb_transfer_sequencer       usb_xfer_seqr[2];
          line 30: svt_usb_system_virtual_sequencer usb_sys_seqr[2];
          line 36: svt_apb_master_sequencer apb_seqr;
          line 37: svt_axi_master_sequencer axi_seqr;
          line 39: usb_reg_sequencer reg_seqr;
        and examples/generated_usb_real_evidence_v7/manifest_inputs/
        usb_env_manifest_v7.json's own "connections" entries reference
        exactly these field names (virt_seqr.apb_seqr, virt_seqr.axi_seqr,
        virt_seqr.reg_seqr, virt_seqr.usb_xfer_seqr[{p}],
        virt_seqr.usb_sys_seqr[{p}]) -- fields the old generic seqr_%d path
        can never produce.

        An optional top-level manifest key "virtual_sequencer_fields" -- a
        list of {"class_type": str, "field_name": str, "port_indexed": bool
        (optional, default false), "evidence": str (required, non-empty)}
        dicts -- therefore REPLACES the generic numbered-handle body entirely
        when present and non-empty: one
        `<class_type> <field_name>;` (scalar) or
        `<class_type> <field_name>[<port_count>];` (port_indexed) declaration
        per entry, in manifest order, instead of the old `seqr_%d` handles.
        "port_count" is read from the manifest's own top-level "port_count"
        field, the same way build_phase's port_indexed vip_components and
        _connect_phase's port_indexed connections already do -- not
        re-derived or re-validated separately here.

        "evidence" is REQUIRED and must be a non-empty string -- same
        evidence-required discipline as "connections"
        (MissingVirtualSequencerFieldEvidenceError otherwise, same typed-error
        convention as this module's other errors)."""
        fields = m.get('virtual_sequencer_fields')
        if fields:
            port_count = m.get('port_count')
            field_lines = []
            for f in fields:
                evidence = f.get('evidence')
                if not evidence or not str(evidence).strip():
                    raise MissingVirtualSequencerFieldEvidenceError(
                        "MISSING_VIRTUAL_SEQUENCER_FIELD_EVIDENCE", {
                            "field": f,
                        })
                class_type = f['class_type']
                field_name = f['field_name']
                if f.get('port_indexed'):
                    field_lines.append('  %s %s[%d];' % (class_type, field_name, port_count))
                else:
                    field_lines.append('  %s %s;' % (class_type, field_name))
            handles = '\n'.join(field_lines)
        else:
            handles='\n'.join('  uvm_sequencer_base seqr_%d;' % i for i,_ in enumerate(m.get('interfaces') or [{}]))
        return '''class %s_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils(%s_virtual_sequencer)
%s
  function new(string name="%s_virtual_sequencer", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
''' % (p,p,handles,p)

    def base_vseq(self,m,p):
        """SEQUENCE_BODIES EXTENSION (additive, backward compatible -- a
        manifest with no top-level "virtual_sequences" key, or an empty
        list, is a complete no-op here: this method returns exactly today's
        fixed placeholder base-vseq class text, byte-identical output).

        Before this extension, base_vseq() consulted zero manifest input --
        no `randomize() with {}`, no `uvm_do_with`, no per-step field
        values -- confirmed a defect against real VIP evidence: real
        virtual-sequence bodies (D:/DV/Task/USB/VIP/examples/
        tb_usb_svt_uvm_20_phy/env/usb_directed_transfers_sequence.sv,
        lines 157-325) are `uvm_create`+`fix_anchors()`+
        `randomize() with {field == value; ...}`+status-check+`uvm_send`
        idiom chains, and usb_isoc_sequence.sv (lines 198-206) shows the
        equally real `uvm_do_with(item, {field == value; ...})` idiom.

        An optional top-level manifest key "virtual_sequences" -- a list of
          {"seq_name": str, "evidence": str (required, non-empty),
           "sequencer_handle": str (optional, opaque SV expr the item is
             executed against, e.g. "p_sequencer.xfer_sequencer"),
           "item_class": str (optional, default item class for this
             sequence's steps, e.g. "svt_usb_transfer"),
           "steps": [
             {"step_name": str, "item_class": str (optional, overrides the
                sequence-level default for this one step),
              "emit_style": "randomize_with" (default) | "uvm_do_with",
              "pre_actions": [str, ...] (optional, opaque verbatim SV
                statements emitted before randomize(), e.g. a
                `fix_anchors()` call that must run first),
              "field_values": [{"field": str, "value": str}, ...] (each
                pair becomes one `field == value;` constraint line, in
                manifest order -- "value" starting with "$" or "@" and
                otherwise a single identifier is a reference token (an
                external testcase/manifest parameter, or a same-sequence
                capture/post_action-defined local variable respectively)
                and is emitted as the bare identifier; any other "value" is
                a verbatim SV expression, e.g. "16'h0100" or
                "svt_usb_types::GET_DESCRIPTOR"),
              "capture": [{"name": str, "from_expr": str}, ...] (optional,
                only meaningful with emit_style "randomize_with": declares
                a sequence-local variable populated, after the randomize+
                status-check, from a verbatim SV expression reading back a
                field of the just-randomized item -- e.g. a response byte),
              "wait_conditions": [{"expr": str, "evidence": str}, ...]
                (optional, opaque blocking SV statement(s) emitted, each
                with its evidence as a `// evidence: ...` comment, before
                the step's item is created/issued),
              "post_actions": [str | {"expr": str, "evidence": str}, ...]
                (optional, only meaningful with emit_style
                "randomize_with": opaque verbatim SV statement(s) emitted
                after the randomize+status-check+capture, before
                `uvm_send` -- e.g. propagating a value produced by this
                step, such as a new device address, into a local variable
                later steps' field_values reference via "@name")
             }, ...
           ]}
        dicts -- drives real emitted sequence-body content instead of
        today's fixed placeholder. Real evidence for the value-propagation
        need ("$name"/"@name"/capture/post_actions): USB 2.0 spec section
        9.4.6 (p.256) -- a device does not change its address until after a
        SET_ADDRESS control transfer's Status stage completes, so that
        transfer itself must still address the OLD value while every
        subsequent step must use the NEW one -- steps are not independent,
        a later step's field can depend on an earlier step's outcome.

        "evidence" is REQUIRED and must be a non-empty string per
        "virtual_sequences" entry -- same evidence-required discipline as
        "connections"/"virtual_sequencer_fields"
        (MissingSequenceBodyEvidenceError otherwise, same typed-error
        convention as this module's other errors). Each "steps[].
        field_values" entry must be a well-formed {"field", "value"} dict
        (MalformedSequenceFieldValueError otherwise -- a constraint line is
        never emitted from a guessed/incomplete entry).

        Emitted classes each `extend %s_base_vseq` (so they inherit its
        `uvm_declare_p_sequencer`), one class per "virtual_sequences" entry,
        appended after the unchanged base-vseq placeholder class in this
        same returned/written file -- manifest order preserved verbatim,
        never reordered.

        "sequencer_handle", when set, selects the real UVM macro variants
        that take an explicit sequencer (`uvm_create_on`/`uvm_send_on`/
        `uvm_do_on_with`) instead of the implicit-default-sequencer forms
        (`uvm_create`/`uvm_send`/`uvm_do_with`) -- both macro families are
        real, standard UVM macros; which one applies is a manifest-level
        fact (whether this virtual sequence's items must be routed to a
        specific sub-sequencer), not a generator guess.

        See _emit_virtual_sequence for the exact emitted shape."""
        base = '''class %s_base_vseq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(%s_base_vseq)
  `uvm_declare_p_sequencer(%s_virtual_sequencer)
  function new(string name="%s_base_vseq"); super.new(name); endfunction
  virtual task body();
    `uvm_info(get_type_name(), "Base virtual sequence started", UVM_MEDIUM)
  endtask
endclass
''' % (p,p,p,p)
        vseqs = m.get('virtual_sequences')
        if not vseqs:
            return base
        parts = [base]
        for vs in vseqs:
            evidence = vs.get('evidence')
            if not evidence or not str(evidence).strip():
                raise MissingSequenceBodyEvidenceError("MISSING_SEQUENCE_BODY_EVIDENCE", {
                    "virtual_sequence": vs,
                })
            parts.append(self._emit_virtual_sequence(p, vs))
        return '\n'.join(parts)

    @staticmethod
    def _resolve_field_value(value):
        """Implements the "value" reference convention documented in
        base_vseq: a value string that is EXACTLY "$identifier" or
        "@identifier" (nothing else in the string) is a reference token --
        an external testcase/manifest parameter ("$") or a same-sequence
        capture/post_action-defined local variable ("@") -- and is emitted
        as the bare identifier. Anything else (including a string that
        merely contains a "$"/"@" as part of a larger verbatim SV
        expression, e.g. a `$sformatf(...)` call some future manifest might
        legitimately place in a "value") is left untouched: this narrow,
        whole-string match is deliberate so a real SV system-task call is
        never mistaken for the reference-token shorthand."""
        s = str(value)
        if re.match(r'^[$@]\w+$', s):
            return s[1:]
        return s

    def _emit_virtual_sequence(self, p, vs):
        """Emits one `class <seq_name> extends <p>_base_vseq` per
        base_vseq's "virtual_sequences" entry -- see that method's
        docstring for the full field-by-field schema. Per step, in
        manifest order:

          "randomize_with" (default emit_style) mirrors
          usb_directed_transfers_sequence.sv:157-325 almost line-for-line:
            <item_class> <step_name>_xfer;
            [wait_conditions...]
            `uvm_create[_on](<step_name>_xfer[, <sequencer_handle>])
            <step_name>_xfer.cfg = cfg;
            [pre_actions...]
            status = <step_name>_xfer.randomize() with { <field == value;>* };
            if (!status) `uvm_fatal("body", "<step_name> Randomization failed!!!")
            [capture[] as "<name> = <from_expr>;"]
            [post_actions...]
            `uvm_send[_on](<step_name>_xfer[, <sequencer_handle>])

          "uvm_do_with" mirrors usb_isoc_sequence.sv:198-206:
            <item_class> <step_name>_xfer;
            [wait_conditions...]
            `uvm_do[_on]_with(<step_name>_xfer[, <sequencer_handle>], { <field == value;>* })

        A `bit status;` local is declared once (only when at least one step
        uses "randomize_with"), and one `int <name>;` local is declared for
        every distinct capture[].name and every distinct "@name" reference
        found in any step's field_values -- the generic `int` type is a
        deliberate protocol-agnostic default (this DSL carries no per-field
        bit-width evidence to pick a narrower type from)."""
        seq_name = vs['seq_name']
        default_item_class = vs.get('item_class', 'uvm_sequence_item')
        sequencer_handle = vs.get('sequencer_handle')
        steps = vs.get('steps') or []

        capture_names = []
        at_ref_names = []
        needs_status = False
        step_blocks = []

        for step in steps:
            step_name = step['step_name']
            item_class = step.get('item_class', default_item_class)
            emit_style = step.get('emit_style', 'randomize_with')
            xfer = '%s_xfer' % step_name

            constraint_lines = []
            for fv in (step.get('field_values') or []):
                if not isinstance(fv, dict) or not fv.get('field') or 'value' not in fv:
                    raise MalformedSequenceFieldValueError("MALFORMED_SEQUENCE_FIELD_VALUE", {
                        "seq_name": seq_name, "step_name": step_name, "field_value": fv,
                    })
                raw_value = fv['value']
                resolved = self._resolve_field_value(raw_value)
                if re.match(r'^@\w+$', str(raw_value)) and resolved not in at_ref_names:
                    at_ref_names.append(resolved)
                constraint_lines.append('      %s == %s;' % (fv['field'], resolved))
            constraints = '\n'.join(constraint_lines)

            for cap in (step.get('capture') or []):
                name = cap.get('name')
                if name and name not in capture_names:
                    capture_names.append(name)

            block = ['    %s %s;' % (item_class, xfer)]
            for wc in (step.get('wait_conditions') or []):
                expr = wc.get('expr')
                if not expr:
                    continue
                if wc.get('evidence'):
                    block.append('    // evidence: %s' % wc['evidence'])
                block.append('    %s' % expr)

            if emit_style == 'uvm_do_with':
                if sequencer_handle:
                    block.append('    `uvm_do_on_with(%s, %s, {' % (xfer, sequencer_handle))
                else:
                    block.append('    `uvm_do_with(%s, {' % xfer)
                block.append(constraints)
                block.append('    })')
            else:
                needs_status = True
                if sequencer_handle:
                    block.append('    `uvm_create_on(%s, %s)' % (xfer, sequencer_handle))
                else:
                    block.append('    `uvm_create(%s)' % xfer)
                block.append('    %s.cfg = cfg;' % xfer)
                for pa in (step.get('pre_actions') or []):
                    block.append('    %s' % pa)
                block.append('    status = %s.randomize() with {' % xfer)
                block.append(constraints)
                block.append('    };')
                block.append('    if (!status) `uvm_fatal("body", "%s Randomization failed!!!")' % step_name)
                for cap in (step.get('capture') or []):
                    block.append('    %s = %s;' % (cap['name'], cap['from_expr']))
                for pa in (step.get('post_actions') or []):
                    if isinstance(pa, dict):
                        if pa.get('evidence'):
                            block.append('    // evidence: %s' % pa['evidence'])
                        block.append('    %s' % pa.get('expr', ''))
                    else:
                        block.append('    %s' % pa)
                if sequencer_handle:
                    block.append('    `uvm_send_on(%s, %s)' % (xfer, sequencer_handle))
                else:
                    block.append('    `uvm_send(%s)' % xfer)

            step_blocks.append('\n'.join(block))

        locals_decl = []
        if needs_status:
            locals_decl.append('    bit status;')
        for name in capture_names:
            locals_decl.append('    int %s;' % name)
        for name in at_ref_names:
            if name not in capture_names:
                locals_decl.append('    int %s;' % name)

        body = '\n'.join(locals_decl + step_blocks)

        return '''class %s extends %s_base_vseq;
  `uvm_object_utils(%s)
  function new(string name="%s"); super.new(name); endfunction
  virtual task body();
%s
  endtask
endclass
''' % (seq_name, p, seq_name, seq_name, body)

    def scoreboard(self,m,p):
        """SCOREBOARD_CHECKS DSL EXTENSION (additive, backward compatible --
        a "scoreboard_rules" entry with no "check_name" key behaves exactly
        as before: comment-dumped as `// RULE: <json>`, byte-identical
        output for every existing manifest, since none of them use this
        key -- confirmed against every examples/generated_usb_real_evidence_v*
        manifest_inputs/*.json this session, all of which are plain
        {"TODO": "..."} dicts).

        Before this extension, scoreboard() did nothing but json.dumps each
        "scoreboard_rules" entry into a comment line inside an otherwise
        empty uvm_scoreboard class body -- no real comparison, no
        `uvm_error`, no register decode (confirmed, this task's own
        read-first pass).

        This closes that gap using the DSL produced by a DUT-RTL+VIP-only
        design pass (D:/DV/Task/USB/DUT's udc_DWC_usb31 EPTYPE/MPS DEPCFG
        fields vs. D:/DV/Task/USB/VIP's svt_usb_endpoint_configuration/
        svt_usb_types, cross-checked against D:/DV/Task/USB/DOC's
        DWC_usb31_programming.txt). A "scoreboard_rules" entry that is a
        dict AND carries a "check_name" key opts into this structured shape
        (chosen as the discriminator, mirroring the "kind" field already
        used to disambiguate schema variants elsewhere in this file, e.g.
        _connect_phase's "kind": "assign"|"construct"|"call" -- an old-style
        freeform rule dict, per every real manifest above, never carries a
        "check_name" key, so there is no ambiguity):

          {"check_name": str (required, non-empty),
           "lhs_source": {"component": str, "field": str,
                          "register_decode": {"bit_offset": int>=0,
                                               "bit_width": int>0} (optional),
                          "enum_translation": <see below> (optional)},
           "rhs_source": <same shape as lhs_source>,
           "compare_op": "eq"|"neq"|"lt"|"lte"|"gt"|"gte"|"mask_eq",
           "mask": str (required, verbatim SV expr, only when
                        compare_op=="mask_eq"),
           "on_mismatch": {"severity": "UVM_ERROR"|"UVM_WARNING"|"UVM_INFO",
                           "message_template": str (required, non-empty)}}

        Each opted-in entry compiles (via _emit_scoreboard_check) into a
        real `function void check_<check_name>(...)` appended to the
        uvm_scoreboard class body, after the unchanged comment-dump/
        placeholder text -- same additive-splice technique as env()'s own
        connect_phase-append (see that method), so entries that do NOT
        opt in are completely unaffected, in position or content.

        Each side's "field" is read directly (`int'(<component>_<field>)`,
        generic `int` default -- same protocol-agnostic default already
        used by _emit_virtual_sequence's capture/at_ref locals -- or an
        explicit "sv_type" override, e.g. "svt_usb_types::ep_type_enum")
        unless "register_decode" is present, in which case it is read as a
        raw `bit[31:0]` register-value parameter and sliced to
        `<field>[bit_offset+bit_width-1:bit_offset]` -- concretely the
        `bit [1:0] lhs = dut_depcmdpar0[2:1];` shape from this task's own
        DSL spec, generalized from EPTYPE's bit_offset=1/bit_width=2.

        "enum_translation" (either side) is ALWAYS compiled into a real
        `case` statement mapping raw value -> translated value, even when
        the map is a numeric identity -- this is a deliberate, spec-mandated
        choice, not an oversight: the DSL spec's own EPTYPE finding is that
        USB's DUT/DOC/VIP values happen to agree numerically, but that this
        is NOT discoverable from the VIP enum's textual declaration order
        alone and must be verified per-protocol/per-VIP-version from real
        evidence, never assumed generically -- so this generator always
        executes the compiled map at runtime instead of ever skipping it as
        an "optimization" for the identity case. Only "kind": "value_map" is
        currently supported (MalformedScoreboardCheckError otherwise); "map"
        must be a non-empty dict; "note" must be a non-empty string (the
        same evidence-citation discipline this generator already requires
        of "connections"/"virtual_sequencer_fields"/"virtual_sequences"
        evidence strings, applied here to why a cross-domain value mapping
        is correct). An unmapped raw value at runtime is NOT silently
        passed through uncounted: the compiled `default:` arm both falls
        back to the raw value (so the subsequent compare still runs, rather
        than leaving the variable undriven) AND raises its own `uvm_error`
        flagging the specific unmapped value -- an enum value the design
        pass never accounted for is itself real evidence of a defect
        (either in the DSL's map or in the DUT/VIP), not something to
        compare through silently.

        message_template's `$sformatf` argument list is ALWAYS exactly
        `(check_name, lhs, rhs)` -- 3 positional args, in that order -- a
        deliberate, documented deviation from the DSL spec's own illustrative
        compiled-code sketch (which additionally interpolates an "ep_id"
        variable): "ep_id" names no field anywhere in this DSL's own
        lhs_source/rhs_source/check-level schema, so it cannot be
        mechanically resolved from the manifest -- it is scratch context the
        spec's sketch assumed was in scope, not a modeled DSL field. Using
        `check_name` (always available, always a stable identifying string)
        in its place keeps message_template mechanically fillable from only
        what this DSL actually models, at the cost of the exact 4-slot
        %s/%0d/%s/%0d shape the spec's sketch showed not being reproducible
        verbatim; a manifest author's message_template must therefore use
        exactly 3 format specifiers, in check_name/lhs/rhs order.

        See _emit_scoreboard_check for the exact per-check compiled shape."""
        entries = m.get('scoreboard_rules') or []
        comment_entries = [x for x in entries
                            if not (isinstance(x, dict) and 'check_name' in x)]
        check_entries = [x for x in entries
                          if isinstance(x, dict) and 'check_name' in x]

        rules = '\n'.join('  // RULE: '+json.dumps(x) for x in comment_entries)
        if not rules and not check_entries:
            rules = '  // Protocol-specific checking rules come from the semantic model.'

        out = '''class %s_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(%s_scoreboard)
%s
  function new(string name="%s_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
''' % (p,p,rules,p)

        if check_entries:
            check_text = '\n'.join(self._emit_scoreboard_check(x) for x in check_entries)
            assert out.endswith('endclass\n')
            out = out[:-len('endclass\n')] + check_text + '\nendclass\n'
        return out

    def _emit_scoreboard_check(self, check):
        """Compiles one "check_name"-carrying scoreboard_rules entry (see
        scoreboard()'s own docstring for the full field-by-field schema)
        into one real
          function void check_<check_name>(<lhs param>, <rhs param>);
            <lhs decode/translation>
            <rhs decode/translation>
            if (<compare_op-derived mismatch condition>)
              `uvm_<severity>("<SB_CHECK_NAME>", $sformatf(<message_template>, "<check_name>", lhs, rhs))
          endfunction
        function, raising MalformedScoreboardCheckError (never silently
        skipping or guessing) on any missing/malformed piece -- see that
        error class's own docstring for the exact validation list."""
        check_name = check.get('check_name')
        if not check_name or not str(check_name).strip():
            raise MalformedScoreboardCheckError("MISSING_CHECK_NAME", {"check": check})

        for side_name, source in (('lhs', check.get('lhs_source')), ('rhs', check.get('rhs_source'))):
            if not isinstance(source, dict) or not source.get('component') or not source.get('field'):
                raise MalformedScoreboardCheckError("MALFORMED_SCORE_SOURCE", {
                    "check_name": check_name, "side": side_name + "_source", "value": source,
                })

        compare_op = check.get('compare_op')
        valid_ops = {'eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'mask_eq'}
        if compare_op not in valid_ops:
            raise MalformedScoreboardCheckError("INVALID_COMPARE_OP", {
                "check_name": check_name, "compare_op": compare_op, "valid_ops": sorted(valid_ops),
            })

        on_mismatch = check.get('on_mismatch')
        if not isinstance(on_mismatch, dict):
            raise MalformedScoreboardCheckError("MISSING_ON_MISMATCH", {"check_name": check_name})
        severity = on_mismatch.get('severity')
        valid_severities = {'UVM_ERROR', 'UVM_WARNING', 'UVM_INFO'}
        if severity not in valid_severities:
            raise MalformedScoreboardCheckError("INVALID_MISMATCH_SEVERITY", {
                "check_name": check_name, "severity": severity, "valid_severities": sorted(valid_severities),
            })
        message_template = on_mismatch.get('message_template')
        if not message_template or not str(message_template).strip():
            raise MalformedScoreboardCheckError("MISSING_MISMATCH_MESSAGE_TEMPLATE", {"check_name": check_name})

        mask = None
        if compare_op == 'mask_eq':
            mask = check.get('mask')
            if not mask or not str(mask).strip():
                raise MalformedScoreboardCheckError("MISSING_MASK_EQ_MASK", {"check_name": check_name})

        params = []
        decl_lines = []

        def emit_side(source, side_name):
            component = source['component']
            field = source['field']
            param_name = sv_id(component + '_' + field)
            register_decode = source.get('register_decode')
            enum_translation = source.get('enum_translation')

            if register_decode:
                bit_offset = register_decode.get('bit_offset')
                bit_width = register_decode.get('bit_width')
                valid_offset = isinstance(bit_offset, int) and not isinstance(bit_offset, bool) and bit_offset >= 0
                valid_width = isinstance(bit_width, int) and not isinstance(bit_width, bool) and bit_width > 0
                if not valid_offset or not valid_width:
                    raise MalformedScoreboardCheckError("INVALID_REGISTER_DECODE", {
                        "check_name": check_name, "side": side_name, "register_decode": register_decode,
                    })
                msb = bit_offset + bit_width - 1
                lsb = bit_offset
                params.append('bit [31:0] %s' % param_name)
                raw_expr = '%s[%d:%d]' % (param_name, msb, lsb)
                raw_decl_type = 'bit [%d:0]' % (bit_width - 1)
            else:
                sv_type = source.get('sv_type', 'int')
                params.append('%s %s' % (sv_type, param_name))
                raw_expr = 'int\'(%s)' % param_name
                raw_decl_type = 'int'

            if enum_translation:
                kind = enum_translation.get('kind')
                if kind != 'value_map':
                    raise MalformedScoreboardCheckError("UNSUPPORTED_ENUM_TRANSLATION_KIND", {
                        "check_name": check_name, "side": side_name, "kind": kind,
                    })
                value_map = enum_translation.get('map')
                if not isinstance(value_map, dict) or not value_map:
                    raise MalformedScoreboardCheckError("MISSING_ENUM_TRANSLATION_MAP", {
                        "check_name": check_name, "side": side_name,
                    })
                note = enum_translation.get('note')
                if not note or not str(note).strip():
                    raise MalformedScoreboardCheckError("MISSING_ENUM_TRANSLATION_NOTE", {
                        "check_name": check_name, "side": side_name,
                    })
                raw_var = '%s_raw' % side_name
                decl_lines.append('    %s %s = %s; // %s' % (raw_decl_type, raw_var, raw_expr, note))
                decl_lines.append('    int %s;' % side_name)
                decl_lines.append('    case (%s)' % raw_var)
                for k, v in value_map.items():
                    decl_lines.append('      %s: %s = %s;' % (k, side_name, v))
                check_id = ('SB_' + sv_id(check_name)).upper()
                decl_lines.append('      default: begin')
                decl_lines.append('        %s = %s;' % (side_name, raw_var))
                decl_lines.append(
                    '        `uvm_error("%s", $sformatf("%s: unmapped enum_translation value %%0d on %s", %s))'
                    % (check_id, check_name, side_name, raw_var))
                decl_lines.append('      end')
                decl_lines.append('    endcase')
            else:
                decl_lines.append('    %s %s = %s;' % (raw_decl_type, side_name, raw_expr))

        emit_side(check['lhs_source'], 'lhs')
        emit_side(check['rhs_source'], 'rhs')

        if compare_op == 'mask_eq':
            mismatch_expr = '(lhs & (%s)) !== (rhs & (%s))' % (mask, mask)
        else:
            mismatch_expr = {
                'eq': 'lhs !== rhs',
                'neq': 'lhs === rhs',
                'lt': '!(lhs < rhs)',
                'lte': '!(lhs <= rhs)',
                'gt': '!(lhs > rhs)',
                'gte': '!(lhs >= rhs)',
            }[compare_op]

        check_id = ('SB_' + sv_id(check_name)).upper()
        severity_macro = '`uvm_%s' % severity[len('UVM_'):].lower()

        return '''  function void check_%s(%s);
%s
    if (%s)
      %s("%s", $sformatf(%s, "%s", lhs, rhs))
  endfunction''' % (
            sv_id(check_name), ', '.join(params), '\n'.join(decl_lines),
            mismatch_expr, severity_macro, check_id, json.dumps(message_template), check_name)

    def coverage(self,m,p):
        cps='\n'.join('  // COVER: '+json.dumps(x) for x in m.get('coverage_points',[]))
        if not cps: cps='  // Protocol-specific coverage comes from the semantic model.'
        return '''class %s_coverage extends uvm_component;
  `uvm_component_utils(%s_coverage)
%s
  function new(string name="%s_coverage", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
''' % (p,p,cps,p)

    def env(self,m,p):
        # ADDITIVE schema extension (multi-component vip_components list):
        # when present and non-empty, this REPLACES the old single vip
        # agent_type/agent_instance slot below in the emitted composition.
        # The single-slot path (no vip_components key, or an empty list) is
        # untouched -- same template, same output, byte-identical to before.
        vip_components = m.get('vip_components')
        if vip_components:
            out = self._env_multi_component(m, p, vip_components)
        else:
            vip=m.get('vip',{})
            at=vip.get('agent_type','uvm_agent')
            ai=vip.get('agent_instance','vip_agent')
            out = '''class %s_env extends uvm_env;
  `uvm_component_utils(%s_env)
  %s_config cfg;
  %s_virtual_sequencer vseqr;
  %s_scoreboard sb;
  %s_coverage cov;
  %s %s;

  function new(string name="%s_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(%s_config)::get(this,"","cfg",cfg))
      cfg=%s_config::type_id::create("cfg");
    vseqr=%s_virtual_sequencer::type_id::create("vseqr",this);
    sb=%s_scoreboard::type_id::create("sb",this);
    cov=%s_coverage::type_id::create("cov",this);
    %s=%s::type_id::create("%s",this);
  endfunction
endclass
''' % (p,p,p,p,p,p,at,ai,p,p,p,p,p,p,ai,at,ai)

        # CONNECTIONS EXTENSION (additive, backward compatible -- a manifest
        # with no top-level "connections" key, or an empty list, is a
        # complete no-op here: _connect_phase returns "" and `out` is
        # returned untouched, byte-identical to before). See
        # _connect_phase's own docstring for the real evidence and the
        # exact emitted shape.
        connect_phase_text = self._connect_phase(m)
        if connect_phase_text:
            assert out.endswith('endclass\n')
            out = out[:-len('endclass\n')] + connect_phase_text + '\nendclass\n'
        return out

    def _connect_phase(self, m):
        """CONNECTIONS EXTENSION: an optional top-level manifest key
        "connections" -- a list of
        {"from": "<lhs SV expr>", "to": "<rhs SV expr>",
         "port_indexed": bool (optional, default false),
         "evidence": "<file:line citation, required, non-empty>"} dicts --
        drives a real connect_phase(uvm_phase phase) function, which today's
        _env_multi_component output does not emit at all (confirmed: no
        "connect_phase" string anywhere in that method before this change).

        Real evidence is USB_UVM_Handoff's usb_top_env.sv connect_phase:
          line 456: function void usb_top_env::connect_phase(uvm_phase phase);
          line 458: super.connect_phase(phase);
          line 472: if (apb_env != null) virt_seqr.apb_seqr = apb_env.master.sequencer;
          line 475: virt_seqr.reg_seqr = reg_seqr;
        and its port-indexed shape, lines 461-465:
          for (int p = 0; p < NUM_USB_PORTS; p++) begin
            if (!cfg.enable_port[p]) continue;
            if (usb_host_agent[p] == null) continue;
            virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;
          end
        Real connect_phase code is a flat list of simple wire-up assignments
        in whatever order the real file has them -- NOT dependency-ordered
        like build_phase's topological_build_order. Connections are
        therefore emitted in manifest order exactly, one assignment per
        entry, never reordered.

        "evidence" is REQUIRED and must be a non-empty string -- a
        connection is never silently accepted without a citation of where it
        came from (MissingConnectionEvidenceError otherwise, same typed-error
        convention as this module's other errors). Each evidence string is
        rendered as a `// evidence: <text>` comment directly above its
        assignment line.

        A connection with "port_indexed": true is wrapped in the SAME
        `for (int p = 0; p < <port_count>; p++)` loop shape already used by
        build_phase above, reusing the manifest's own top-level "port_count"
        value (the same field build_phase's port-indexed components already
        require/validate via _validate_port_count -- not re-derived
        separately here). Placeholder convention (Python str.format style):
        write a literal `{p}` in "from"/"to" wherever the loop index belongs,
        e.g. "virt_seqr.host_seqr[{p}]" -- the bare `{p}` token is textually
        replaced with the loop variable `p` (any surrounding brackets are
        already part of the manifest string itself, not added by this
        substitution), e.g. "virt_seqr.host_seqr[{p}]" ->
        "virt_seqr.host_seqr[p]".

        Returns "" (no connect_phase function emitted at all) when
        "connections" is absent or an empty list -- fully backward
        compatible, byte-identical output for every manifest that does not
        use this key.

        CALL/CONSTRUCT/GUARD/IFDEF EXTENSION (additive, backward compatible
        -- an entry with no "kind" key, or "kind": "assign" and none of the
        new cross-cutting fields set, behaves exactly as above, producing
        byte-identical output): Multi-Agent Evidence Consensus re-read
        usb_top_env.sv's connect_phase (lines 456-623) and found real
        wire-up statements this generator could not yet emit at all:

          line 506: payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);
          line 508: uvm_callbacks#(svt_usb_protocol)::add(usb_host_agent[p].prot, payload_cb[p]);
          line 531: dma_env.master[p].monitor.item_observed_port.connect(dma_sb[p].dma_export);
          line 535: if (payload_cb[p] != null) payload_cb[p].dma_sb = dma_sb[p];
          line 552: if (dma_env != null && dma_env.master.size() > 0)
                      dma_env.master[0].monitor.item_observed_port.connect(ssmem_sb.dma_export_p0);

        Every "connections" entry now optionally carries:

          "kind": "assign" | "construct" | "call" (optional, default
          "assign" -- an entry with no "kind" key is unaffected).

          "construct" is for assignment-syntax statements whose RHS is a
          `new(...)` call (line 506): {"lhs": <SV expr str>,
          "ctor_args": [<verbatim arg expr str>, ...]} (ctor_args optional,
          omitted/empty emits a bare `new()`). Emits `<lhs> = new(<args>);`.
          "ctor_class" is accepted (per the consensus spec, resolved from
          the real member's declared type) but is documentation-only here:
          nothing in this generator's emitted SV text needs the declared
          type name, since `new(...)` itself carries no type token -- it is
          not rendered, only accepted so a manifest carrying it is not
          rejected.

          "call" is for statements with no assignment at all (lines 508,
          531, 552, 554): {"call_style": "static" | "instance",
          "class_scope": <str, required when call_style=="static">,
          "receiver": <str, required when call_style=="instance">,
          "method": <str>, "args": [<verbatim arg expr str>, ...]}.
          Emits `<class_scope>::<method>(<args>);` (static) or
          `<receiver>.<method>(<args>);` (instance).

          "guard": [<verbatim runtime `if` condition str>, ...] (optional,
          default/empty = unconditional). Multiple entries are ANDed.
          Rendering choice, deliberately verified against real evidence
          rather than guessed: a SINGLE combined `if (<cond1> && <cond2>
          && ...) <stmt>;` line, not nested `if` blocks. This is confirmed
          correct, not just plausible, for every single-guard statement in
          the table above by direct comparison against the real flattened
          source text -- e.g. line 535's real text IS exactly
          `if (payload_cb[p] != null) payload_cb[p].dma_sb = dma_sb[p];`,
          which is precisely what a single combined `if` produces when
          guard has one entry. For the one multi-guard case in real
          evidence (lines 552/554), the real source nests two separate
          `if`s wrapping TWO SIBLING statements sharing one outer
          condition -- but each connections entry here models ONE
          statement independently (no cross-entry sharing exists in this
          schema), so reproducing that exact nested shape is not
          expressible without inventing statement-grouping the spec never
          asked for. AND-joining with `&&` into one `if` is logically
          equivalent (both conditions must hold) and is the natural
          per-statement rendering of "ANDed" -- adopted deliberately, not
          silently.

          "loop_var": accepted (per the consensus spec, "index variable of
          the innermost enclosing for/foreach"). Every real statement this
          round models that has a loop var uses "p" -- the same literal
          the existing "port_indexed" for-loop below already hardcodes.
          This field is therefore accepted as documentation/traceability
          metadata only; it does not rename the emitted loop variable
          (there is no real-evidence case in this manifest schema needing
          any variable other than "p", and every other "port_indexed" user
          in this file -- build_phase's own per-port loops -- is equally
          hardcoded to "p").

          "ifdef_macro": <macro name str> | None (optional). REUSES the
          identical field name/shape already used per-component in
          _env_multi_component (see that method's own IFDEF-MACRO
          EXTENSION docstring) -- same `` `ifdef <MACRO>``/`` `endif``
          wrapping, applied around this one connection's whole emitted
          block (for-loop included, when also port_indexed). Orthogonal to
          "guard": line 535 is the proof this must not collapse into the
          "call" kind -- it stays "kind":"assign" while carrying
          "ifdef_macro" and "guard" both.

        "evidence" remains REQUIRED and non-empty for every kind, unchanged
        (MissingConnectionEvidenceError) -- construct/call entries are not
        exempt. No new typed error class is introduced by this extension:
        the consensus spec defines no additional validation beyond the
        pre-existing evidence requirement.

        The "line" and "raw_text" fields the consensus spec also lists as
        cross-cutting are accepted (any manifest entry may carry them) but
        are NOT rendered into the emitted SV text: no field in the
        pre-existing "connections" schema is echoed into output verbatim
        either (only "evidence" is, as a `// evidence: ...` comment) --
        "line"/"raw_text" are traceability metadata for a schema consumer,
        not additional text this generator must print.

        The {p} placeholder substitution described above for "from"/"to"
        applies identically, when "port_indexed" is set, to every
        string-valued field of the new kinds and to "guard" entries:
        "lhs", "ctor_args", "class_scope", "receiver", "method", "args",
        each entry of "guard".
        """
        connections = m.get('connections')
        if not connections:
            return ''
        port_count = m.get('port_count')
        lines = ['  function void connect_phase(uvm_phase phase);',
                 '    super.connect_phase(phase);']
        for conn in connections:
            evidence = conn.get('evidence')
            if not evidence or not str(evidence).strip():
                raise MissingConnectionEvidenceError("MISSING_CONNECTION_EVIDENCE", {
                    "connection": conn,
                })
            kind = conn.get('kind', 'assign')
            port_indexed = bool(conn.get('port_indexed'))

            def sub(s):
                return s.replace('{p}', 'p') if port_indexed else s

            if kind == 'assign':
                stmt = '%s = %s;' % (sub(conn['from']), sub(conn['to']))
            elif kind == 'construct':
                ctor_args = ', '.join(sub(a) for a in (conn.get('ctor_args') or []))
                stmt = '%s = new(%s);' % (sub(conn['lhs']), ctor_args)
            elif kind == 'call':
                method = sub(conn['method'])
                args = ', '.join(sub(a) for a in (conn.get('args') or []))
                if conn.get('call_style') == 'static':
                    stmt = '%s::%s(%s);' % (sub(conn['class_scope']), method, args)
                else:
                    stmt = '%s.%s(%s);' % (sub(conn['receiver']), method, args)
            else:
                raise ValueError('unknown connection kind: %r' % (kind,))

            guard = conn.get('guard') or []
            if guard:
                cond = ' && '.join(sub(g) for g in guard)
                stmt = 'if (%s) %s' % (cond, stmt)

            ifdef_macro = conn.get('ifdef_macro')
            body_indent = '      ' if port_indexed else '    '
            block = []
            if ifdef_macro:
                block.append('`ifdef %s' % ifdef_macro)
            if port_indexed:
                block.append('    for (int p = 0; p < %d; p++) begin' % port_count)
            block.append('%s// evidence: %s' % (body_indent, evidence))
            block.append('%s%s' % (body_indent, stmt))
            if port_indexed:
                block.append('    end')
            if ifdef_macro:
                block.append('`endif')
            lines.extend(block)
        lines.append('  endfunction')
        return '\n'.join(lines)

    def _validate_port_count(self, m, vip_components):
        """Additive schema check for the port_indexed extension: any
        component with "port_indexed": true requires a top-level manifest
        "port_count" that is a valid positive int -- never a guessed
        default (see InvalidPortCountError). Returns None (and validates
        nothing) when no component in this manifest is port_indexed, so a
        manifest that never uses the new field pays no cost and cannot be
        rejected by it."""
        port_indexed_names = [c['name'] for c in vip_components if c.get('port_indexed')]
        if not port_indexed_names:
            return None
        port_count = m.get('port_count')
        valid = (isinstance(port_count, int)
                  and not isinstance(port_count, bool)
                  and port_count > 0)
        if not valid:
            raise InvalidPortCountError("INVALID_PORT_COUNT", {
                "port_indexed_components": port_indexed_names,
                "port_count": port_count,
            })
        return port_count

    def _construct_collision_targets(self, m):
        """CONSTRUCT/BUILD-PHASE DEDUP EXTENSION (additive, backward
        compatible -- a manifest with no "connections" entries of
        kind="construct" returns an empty dict here, so _env_multi_component's
        collision check below never fires and every existing manifest emits
        byte-identical output).

        Real evidence (Multi-Agent Evidence Consensus, re-verified this
        session against USB_UVM_Handoff's usb_top_env.sv): line 506,
        `payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);`, is the
        ONLY real construction site for payload_cb -- it sits in
        connect_phase, not build_phase, and usb_top_env.sv never constructs
        payload_cb anywhere else. Before this extension, a manifest with
        BOTH a payload_cb vip_components entry (kind="plain_object", which
        always emits its own build_phase `new(...)`) AND a "connections"
        entry with kind="construct" targeting payload_cb[p] (added so
        connect_phase's real statement list is complete) produced TWO
        `new(...)` calls for the same real object -- a defect, confirmed
        against the real file, which constructs it exactly once.

        Returns a dict mapping the array-index-stripped base identifier of
        each kind="construct" connections entry's "lhs" (e.g.
        "payload_cb[{p}]" -> "payload_cb", or a scalar "err_catcher" ->
        "err_catcher" unchanged) to the list of matching connection dicts
        (normally length 1; kept as a list rather than collapsed to the
        first match so a caller reporting a collision can cite every
        colliding entry, not just one). Matching against a vip_components
        entry's own "instance_name" is done by the caller
        (_env_multi_component), not here -- this method only parses
        "connections", independent of vip_components, mirroring how
        _connect_phase itself never looks at vip_components either."""
        connections = m.get('connections') or []
        targets = {}
        for conn in connections:
            if conn.get('kind') != 'construct':
                continue
            lhs = conn.get('lhs', '')
            base = re.sub(r'\[[^\]]*\]$', '', lhs)
            targets.setdefault(base, []).append(conn)
        return targets

    def _env_multi_component(self,m,p,vip_components):
        """Real multi-component composition (USB_UVM_Handoff evidence: ~10
        real sub-components per port with real order-dependency comments
        between their instantiation). Declares one typed handle per
        component using each entry's real class_type/instance_name VERBATIM
        (never invented), and creates each component in the manifest's
        computed topological build order, with a comment on each create()
        citing the depends_on entries that justify its position -- the
        concrete, generated form of the real env's own ordering-dependency
        include comments.

        PORT-INDEXED EXTENSION (additive, backward compatible -- a component
        without "port_indexed": true behaves exactly as above): when a
        component sets "port_indexed": true, it is declared as a real SV
        array (`<class_type> <instance_name>[<port_count>];`) instead of a
        scalar handle, and its build_phase creation is a
        `for (int p = 0; p < <port_count>; p++)` loop creating
        `<instance_name>[p] = <class_type>::type_id::create($sformatf("<instance_name>_%0d", p), this);`
        -- the standard UVM per-port array idiom, confirmed against the real
        USB_UVM_Handoff usb_top_env.sv (e.g. lines 407-414: `port_name =
        $sformatf("usb_host_agent_%0d", p); usb_host_agent[p] =
        svt_usb_agent::type_id::create(port_name, this);` inside a
        `for (int p = 0; p < NUM_USB_PORTS; p++)` loop). topological_build_order
        treats a port_indexed component as ONE node (already true above: the
        function only ever looks at `name`/`depends_on`), so its whole
        per-port loop lands together at its one topologically-correct
        position -- no per-port-instance dependency resolution is attempted.

        INTERFACE-KIND EXTENSION (additive, backward compatible -- a
        component without "kind": "interface" behaves exactly as above; the
        implicit default kind, when "kind" is omitted, remains today's
        class-handle/agent kind): real evidence is USB_UVM_Handoff's
        usb_top_env.sv:75, `virtual svt_usb_if usb_if[NUM_USB_PORTS];` -- a
        virtual SystemVerilog interface handle, declared but never
        `::type_id::create()`-ed (a virtual interface is bound externally,
        not built by the factory). Its value instead arrives via
        uvm_config_db, confirmed at usb_top_env.sv:372-377 (inside a
        `for (int p = 0; p < NUM_USB_PORTS; p++)` loop):
            if (!uvm_config_db#(virtual svt_usb_if)::get(null, get_full_name(),
                                                         port_name, usb_if[p])) begin
              `uvm_fatal("build_phase", ...)
            end
        A component with "kind": "interface" therefore emits a
        `virtual <class_type> <instance_name>;` (or, combined with
        "port_indexed": true, `virtual <class_type> <instance_name>[<port_count>];`)
        DECLARATION ONLY -- no create() and no for-loop-creation code -- and
        its build_phase line is a uvm_config_db#(virtual <class_type>)::get()
        with a `uvm_fatal` on failure instead of a create() call (scalar), or
        that same get() performed per-port inside a
        `for (int p = 0; p < <port_count>; p++)` loop keyed by
        `$sformatf("<instance_name>_%0d", p)` (port_indexed).

        IFDEF-MACRO EXTENSION (additive, backward compatible -- a component
        without "ifdef_macro" set behaves exactly as above): real evidence is
        USB_UVM_Handoff's usb_top_env.sv, where `usb_dma_ssmem_scoreboard
        ssmem_sb;` is declared at line 128 inside an
        `` `ifdef USB_UVM_DMA_MON `` / `` `endif `` guard (lines 120-129), and
        `ssmem_sb` is created at line 366 inside that SAME
        `` `ifdef USB_UVM_DMA_MON `` guard in build_phase (lines 356-367) --
        both the declaration and the creation gated behind one compile-time
        macro, never emitted unconditionally. A component with
        "ifdef_macro": "<MACRO_NAME>" set therefore has BOTH its declaration
        line and its build_phase creation/config_db-get code wrapped in
        `` `ifdef <MACRO_NAME> `` / `` `endif `` guards.

        CONFIG_DB_KEY_PATTERN EXTENSION (additive, backward compatible -- a
        component without "config_db_key_pattern" set behaves exactly as
        above, using the generator's own guessed "<instance_name>_%0d"
        default): the guessed default does NOT match real evidence. Re-verified
        against USB_UVM_Handoff's usb_top_env.sv:371-377 this session: the
        real per-port virtual-interface get() key is built at line 371 as
        `port_name = $sformatf("usb%0d_if", p);` -- literally "usb%0d_if",
        with %0d embedded before a fixed "_if" suffix, not
        "<instance_name>_%0d" (the real instance_name is `usb_if`, so the
        generator's guessed default would wrongly produce "usb_if_%0d", i.e.
        keys "usb_if_0"/"usb_if_1" instead of the real "usb0_if"/"usb1_if").
        A component may set "config_db_key_pattern" to a %-style format string
        containing one %d/%0d placeholder (e.g. "usb%0d_if") to use verbatim,
        via $sformatf, instead of the guessed default -- for BOTH the
        port_indexed get() (formatted with the loop variable `p`) and the
        scalar get() (formatted with no arguments, since there is no port
        index; the scalar default with the field absent remains the original
        bare quoted instance_name, no $sformatf wrapper, unchanged).

        PLAIN_OBJECT EXTENSION (additive, backward compatible -- a component
        without "kind": "plain_object" behaves exactly as above): real
        evidence is USB_UVM_Handoff's usb_top_env.sv:178/182
        (`svt_err_catcher err_catcher;` constructed as
        `err_catcher = new({get_full_name(), ".err_catcher"});`, in the env's
        own `function new()`, never `::type_id::create()`-ed -- svt_err_catcher
        is used directly, not subclassed) and usb_top_env.sv:85/506
        (`usb_payload_publish_cb payload_cb [2];`, constructed per-port as
        `payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);` inside a
        `foreach` in connect_phase). Both are genuine non-uvm_component fields
        built via a direct new() call rather than the factory. The real new()
        calls sit in usb_top_env's own constructor/connect_phase, not
        build_phase; this generator always emits its instantiation in
        build_phase regardless (a generator-composition choice), reproducing
        only the "plain new(), not type_id::create()" shape and the real
        constructor-arg lists, not the real file's phase placement. A
        component with "kind": "plain_object" therefore emits a declaration
        identical to the default class-handle kind (`<class_type>
        <instance_name>;`, or the port_indexed array form), but its
        build_phase creation is `<instance_name> = new(<args>);` (scalar) or,
        combined with "port_indexed": true, a `for` loop calling
        `<instance_name>[p] = new(<args>);` per port -- confirmed
        port-indexed by the real payload_cb evidence above. <args> comes from
        an optional "constructor_args" list of raw SV expression strings,
        comma-joined verbatim (an arg may reference the loop variable `p`
        directly, as the real payload_cb call does); omitted or empty emits a
        bare new().

        CONSTRUCT/BUILD-PHASE DEDUP EXTENSION (additive, backward compatible
        -- a manifest with no colliding "connections" kind="construct" entry
        behaves exactly as above): see _construct_collision_targets' own
        docstring for the real evidence (payload_cb's ONLY real construction
        site is usb_top_env.sv:506, in connect_phase, never build_phase). A
        "plain_object" component whose instance_name collides with a
        kind="construct" connections entry's "lhs" (array-index suffix
        stripped) has its build_phase creation SKIPPED ENTIRELY (declaration
        kept; connect_phase's own emitted `new(...)` from that connections
        entry is the sole construction site) -- mirroring the existing
        cfg/vseqr/sb/cov reserved-name-collision mechanism further down this
        same method (same shape of problem: two schema paths independently
        deciding to construct the same real object; the manifest-supplied,
        more-specific path wins, the generic path is skipped rather than
        emitting a duplicate). A non-"plain_object" component (class-handle
        or "interface" kind) colliding the same way raises
        ConstructionCollisionError instead of silently skipping: for those
        kinds, build_phase IS the only real construction site
        (::type_id::create() / config_db get()), so a colliding "construct"
        connections entry is not a documented real pattern but a manifest
        authoring mistake that must not pass silently."""
        order = topological_build_order(vip_components)
        by_name = {c['name']: c for c in vip_components}
        port_count = self._validate_port_count(m, vip_components)

        decl_lines = []
        for n in order:
            c = by_name[n]
            is_if = c.get('kind') == 'interface'
            vpfx = 'virtual ' if is_if else ''
            ifdef_macro = c.get('ifdef_macro')
            if ifdef_macro:
                decl_lines.append('`ifdef %s' % ifdef_macro)
            if c.get('port_indexed'):
                decl_lines.append('  %s%s %s[%d];' % (
                    vpfx, c['class_type'], c['instance_name'], port_count))
            else:
                decl_lines.append('  %s%s %s;' % (
                    vpfx, c['class_type'], c['instance_name']))
            if ifdef_macro:
                decl_lines.append('`endif')
        decls = '\n'.join(decl_lines)

        construct_collision_targets = self._construct_collision_targets(m)

        create_lines = []
        for n in order:
            c = by_name[n]
            is_if = c.get('kind') == 'interface'
            is_plain = c.get('kind') == 'plain_object'

            colliding_constructs = construct_collision_targets.get(c['instance_name'])
            if colliding_constructs:
                if is_plain:
                    # DEFECT FIX (real evidence: USB_UVM_Handoff's
                    # usb_top_env.sv constructs payload_cb[p] exactly ONCE,
                    # at connect_phase line 506 -- there is no separate
                    # build_phase construction). The matching kind="construct"
                    # connections entry is the sole construction site; skip
                    # this component's build_phase creation entirely (its
                    # declaration above is untouched).
                    continue
                raise ConstructionCollisionError("AMBIGUOUS_CONSTRUCT_COLLISION", {
                    "component": c['name'],
                    "instance_name": c['instance_name'],
                    "kind": c.get('kind', 'class_handle'),
                    "colliding_connections": colliding_constructs,
                })

            ifdef_macro = c.get('ifdef_macro')
            deps = c.get('depends_on') or []
            if deps:
                comment = '    // after %s (depends_on)' % ', '.join(deps)
            else:
                comment = '    // no depends_on'
            if ifdef_macro:
                create_lines.append('`ifdef %s' % ifdef_macro)
            create_lines.append(comment)
            if c.get('port_indexed'):
                create_lines.append('    for (int p = 0; p < %d; p++) begin' % port_count)
                if is_if:
                    # CONFIG_DB_KEY_PATTERN EXTENSION (additive, backward
                    # compatible -- a component without "config_db_key_pattern"
                    # behaves exactly as before): real evidence is
                    # USB_UVM_Handoff's usb_top_env.sv:371-377, which does NOT
                    # use the generator's default "<instance_name>_%0d" shape
                    # (that would be "usb_if_%0d") but instead
                    #   port_name = $sformatf("usb%0d_if", p);
                    #   uvm_config_db#(virtual svt_usb_if)::get(null,
                    #     get_full_name(), port_name, usb_if[p])
                    # i.e. the literal pattern "usb%0d_if" (line 371), where
                    # %0d is embedded before a fixed "_if" suffix rather than
                    # appended after "<instance_name>_". A manifest may supply
                    # this real pattern verbatim via "config_db_key_pattern" so
                    # the emitted $sformatf() matches the real key shape
                    # instead of the generator's guessed default.
                    key_pattern = c.get('config_db_key_pattern') or (
                        '%s_%%0d' % c['instance_name'])
                    create_lines.append(
                        '      if (!uvm_config_db#(virtual %s)::get(this, "", $sformatf("%s", p), %s[p]))' % (
                            c['class_type'], key_pattern, c['instance_name']))
                    create_lines.append(
                        '        `uvm_fatal(get_type_name(), "virtual interface %s not found in config_db")' % (
                            c['instance_name']))
                elif is_plain:
                    # PLAIN_OBJECT + PORT_INDEXED EXTENSION: real evidence is
                    # USB_UVM_Handoff's usb_top_env.sv:85 (`usb_payload_publish_cb
                    # payload_cb [2];`, a plain non-uvm_component array field)
                    # constructed at line 506 inside a `foreach` loop with a
                    # direct `new(...)` call (not ::type_id::create()):
                    #   payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);
                    # "constructor_args" is an optional list of raw SV
                    # expression strings, comma-joined verbatim into the
                    # emitted new(...) call; an arg string may reference the
                    # loop variable `p` directly (as the real call does),
                    # since it is emitted inside this same for-loop scope.
                    args = ', '.join(c.get('constructor_args') or [])
                    create_lines.append(
                        '      %s[p] = new(%s);' % (c['instance_name'], args))
                else:
                    create_lines.append(
                        '      %s[p] = %s::type_id::create($sformatf("%s_%%0d", p), this);' % (
                            c['instance_name'], c['class_type'], c['instance_name']))
                create_lines.append('    end')
            else:
                if is_if:
                    if c.get('config_db_key_pattern'):
                        key_expr = '$sformatf("%s")' % c['config_db_key_pattern']
                    else:
                        key_expr = '"%s"' % c['instance_name']
                    create_lines.append(
                        '    if (!uvm_config_db#(virtual %s)::get(this, "", %s, %s))' % (
                            c['class_type'], key_expr, c['instance_name']))
                    create_lines.append(
                        '      `uvm_fatal(get_type_name(), "virtual interface %s not found in config_db")' % (
                            c['instance_name']))
                elif is_plain:
                    # PLAIN_OBJECT EXTENSION (additive, backward compatible --
                    # a component without "kind": "plain_object" behaves
                    # exactly as the class-handle default below): real
                    # evidence is USB_UVM_Handoff's usb_top_env.sv:178
                    # (`svt_err_catcher err_catcher;`, a plain non-uvm_component
                    # field -- svt_err_catcher is used directly, never
                    # factory-registered) constructed at line 182 via a direct
                    # `new(...)` call rather than ::type_id::create():
                    #   err_catcher = new({get_full_name(), ".err_catcher"});
                    # (the real call sits in usb_top_env's own `function new()`
                    # constructor, not build_phase -- the generator always
                    # places its emitted instantiation in build_phase
                    # regardless of which phase the cited real call happens to
                    # use; only the "plain new(), not type_id::create()" shape
                    # and the constructor-arg list are reproduced verbatim).
                    # "constructor_args" is an optional list of raw SV
                    # expression strings, comma-joined verbatim into new(...);
                    # when absent, emits a bare new() (the real call's shape
                    # when a component supplies no args).
                    args = ', '.join(c.get('constructor_args') or [])
                    create_lines.append('    %s = new(%s);' % (
                        c['instance_name'], args))
                else:
                    create_lines.append('    %s=%s::type_id::create("%s",this);' % (
                        c['instance_name'], c['class_type'], c['instance_name']))
            if ifdef_macro:
                create_lines.append('`endif')
        creates = '\n'.join(create_lines)

        # BUG FIX (2026-08-29, real-USB-evidence round 3): the fixed
        # boilerplate fields below (cfg/vseqr/sb/cov) are unconditional in
        # the single-slot template this method mirrors -- but a real
        # vip_components entry can legitimately need one of these exact
        # instance_names (confirmed: USB_UVM_Handoff's own usb_top_env.sv
        # names its config handle `cfg`, of real type `usb_top_cfg`), which
        # previously collided with this boilerplate's own `%s_config cfg;`
        # declaration -- two conflicting `cfg` fields in one class is not
        # valid SystemVerilog. A manifest-supplied component now always wins:
        # skip the matching boilerplate line entirely rather than emit a
        # name collision.
        reserved_by_manifest = {c['instance_name'] for c in vip_components} & {'cfg', 'vseqr', 'sb', 'cov'}
        boilerplate_decls = []
        if 'cfg' not in reserved_by_manifest:
            boilerplate_decls.append('  %s_config cfg;' % p)
        if 'vseqr' not in reserved_by_manifest:
            boilerplate_decls.append('  %s_virtual_sequencer vseqr;' % p)
        if 'sb' not in reserved_by_manifest:
            boilerplate_decls.append('  %s_scoreboard sb;' % p)
        if 'cov' not in reserved_by_manifest:
            boilerplate_decls.append('  %s_coverage cov;' % p)
        boilerplate_creates = []
        if 'cfg' not in reserved_by_manifest:
            boilerplate_creates.append(
                '    if(!uvm_config_db#(%s_config)::get(this,"","cfg",cfg))\n      cfg=%s_config::type_id::create("cfg");' % (p, p))
        if 'vseqr' not in reserved_by_manifest:
            boilerplate_creates.append('    vseqr=%s_virtual_sequencer::type_id::create("vseqr",this);' % p)
        if 'sb' not in reserved_by_manifest:
            boilerplate_creates.append('    sb=%s_scoreboard::type_id::create("sb",this);' % p)
        if 'cov' not in reserved_by_manifest:
            boilerplate_creates.append('    cov=%s_coverage::type_id::create("cov",this);' % p)

        return '''class %s_env extends uvm_env;
  `uvm_component_utils(%s_env)
%s
%s

  function new(string name="%s_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
%s
%s
  endfunction
endclass
''' % (p, p, '\n'.join(boilerplate_decls), decls, p, '\n'.join(boilerplate_creates), creates)

    def base_test(self,m,p):
        return '''class %s_base_test extends uvm_test;
  `uvm_component_utils(%s_base_test)
  %s_env env;
  function new(string name="%s_base_test", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env=%s_env::type_id::create("env",this);
  endfunction
endclass
''' % (p,p,p,p,p)

    def smoke_test(self,m,p,n):
        return '''class %s_%s_test extends %s_base_test;
  `uvm_component_utils(%s_%s_test)
  function new(string name="%s_%s_test", uvm_component parent=null); super.new(name,parent); endfunction
  task run_phase(uvm_phase phase);
    %s_base_vseq vseq;
    phase.raise_objection(this);
    vseq=%s_base_vseq::type_id::create("vseq");
    vseq.start(env.vseqr);
    phase.drop_objection(this);
  endtask
endclass
''' % (p,n,p,p,n,p,n,p,p)

    def tb_top(self,m,p,pkg):
        clk=(m.get('clocks') or [{'name':'clk'}])[0].get('name','clk')
        rst=(m.get('resets') or [{'name':'rst_n'}])[0].get('name','rst_n')
        return '''module tb_top;
  import uvm_pkg::*;
  import %s::*;
  logic %s;
  logic %s;
  initial begin %s=0; forever #5 %s=~%s; end
  initial begin %s=0; #100; %s=1; end
  // Bind DUT and VIP interfaces from environment_manifest.json/current evidence.
  initial run_test();
endmodule
''' % (pkg,clk,rst,clk,clk,clk,rst,rst)
