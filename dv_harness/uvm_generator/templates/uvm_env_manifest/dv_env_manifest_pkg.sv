// dv_env_manifest_pkg.sv -- generic, protocol-agnostic UVM capture package
// for two of env.manifest.json's three layers: vip_config and
// env_topology.component_hierarchy (dv_harness/env_manifest.py, the third
// layer, dut_facts, is populated entirely from static tools -- real verible
// --export_json RTL parsing plus a structured register-map input file --
// and needs nothing from this package).
//
// This is a STATIC TEMPLATE, copied verbatim into a generated environment
// (same convention as templates/sim_scripts/validate_run_profile_args.py --
// see run_profile_to_justfile.py's own copy call) -- it is never rendered
// through string substitution. A generated environment's own base_test
// extends dv_env_manifest_base_test (or calls its two dump functions
// directly from its own end_of_elaboration_phase) and each VIP config
// wrapper class calls dv_env_manifest_register_vip_config() once its own
// config object has resolved its real applied values (build_phase or
// connect_phase, before end_of_elaboration_phase runs).
//
// WHY end_of_elaboration_phase: it runs at simulation time 0, after every
// component's build_phase/connect_phase has completed (so every VIP config
// object has already resolved its real values, and the full uvm_top
// hierarchy already exists) but before run_phase starts driving any
// transaction -- the "zero-time" capture point the env.manifest.json design
// requires. Capturing any later risks a config object whose value changed
// mid-test no longer reflecting elaboration-time truth; capturing any
// earlier risks a component that has not built yet.
//
// vip_config capture contract: this package does NOT know how to read any
// specific VIP's config class internals (there is no single stable API a
// generic package could rely on across VIP vendors) -- that per-VIP
// resolution is the generated environment's own responsibility. This
// package only provides the REGISTRATION + DUMP mechanics: a VIP config
// wrapper reports its own already-resolved field name/value pairs once,
// and dv_env_manifest_write_vip_config_dump() serializes whatever was
// registered. A VIP config wrapper that never calls
// dv_env_manifest_register_vip_config() simply does not appear in the
// dump -- env_manifest.py's own parser reports that honestly (an empty
// vip_instances array, or the whole layer NOT_AVAILABLE if the dump file
// itself does not exist), it never fabricates a VIP's config content.
//
// env_topology.component_hierarchy capture contract: unlike vip_config,
// this DOES walk the real uvm_top hierarchy directly (get_children() /
// get_full_name() / get_type_name() / uvm_agent::get_is_active() are
// stable UVM 1.2 API, not per-VIP), so no per-component registration is
// needed for this half. This package deliberately emits its own
// structured JSON here rather than asking env_manifest.py to re-parse
// uvm_top.print_topology()'s free-text table output -- that text format is
// a human-readable report, not a documented machine contract, and this
// project's own "never guess a command contract" discipline (see
// verible_parser.py, memory_vault.py's ObsidianAdapter) applies here too.
// dv_env_manifest_base_test still calls the real uvm_top.print_topology()
// on the same phase, so the human-readable table keeps landing in the sim
// log exactly where the env.manifest.json design's own capture-mechanism
// language names it -- this package's JSON dump is an ADDITIONAL, robustly
// parseable artifact built from the same real uvm_top object, not a
// replacement for it.
//
// +UVM_CONFIG_DB_TRACE needs no code in this package at all -- it is a
// plusarg the UVM library itself already recognizes natively; running the
// generated environment with it set is enough to make the sim log carry
// config_db set/get report lines, which dv_harness/env_manifest.py's
// parse_config_db_trace_log() reads directly from the raw log file (see
// that function's own docstring for exactly how much of that report line
// this parser treats as certain vs. opaque).

package dv_env_manifest_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // ---- vip_config: registration + dump -------------------------------

  // One VIP config object's already-resolved field snapshot, as reported
  // by that VIP's own config wrapper -- never re-derived by this package.
  class dv_env_manifest_vip_entry;
    string instance_path;
    string vip_type;
    string field_names[$];
    string field_values[$];   // field_values[i] is field_names[i]'s value
  endclass

  // Process-global registry (a UVM package has exactly one instance per
  // simulation, so a plain static queue is the whole environment's
  // registry -- no singleton class needed).
  dv_env_manifest_vip_entry dv_env_manifest_vip_registry[$];

  // Called once per VIP config object, from that VIP config wrapper's own
  // build_phase/connect_phase, after its real values have resolved.
  // `field_names`/`field_values` must be the same length; `field_values[i]`
  // is that VIP's own already-stringified applied value for
  // `field_names[i]` (e.g. an enum's `.name()`, an int's `$sformatf("%0d",
  // ...)`) -- this function performs no interpretation of either.
  function automatic void dv_env_manifest_register_vip_config(
      string instance_path, string vip_type,
      string field_names[$], string field_values[$]);
    dv_env_manifest_vip_entry e;
    if (field_names.size() != field_values.size()) begin
      `uvm_error("DV_ENV_MANIFEST",
        $sformatf("dv_env_manifest_register_vip_config: field_names.size=%0d != field_values.size=%0d for %s",
                   field_names.size(), field_values.size(), instance_path))
      return;
    end
    e = new();
    e.instance_path = instance_path;
    e.vip_type = vip_type;
    e.field_names = field_names;
    e.field_values = field_values;
    dv_env_manifest_vip_registry.push_back(e);
  endfunction

  // ---- shared JSON-string helpers ------------------------------------

  function automatic string dv_env_manifest_json_escape(string s);
    string out_str;
    out_str = "";
    for (int i = 0; i < s.len(); i++) begin
      byte c = s.getc(i);
      case (c)
        "\"": out_str = {out_str, "\\\""};
        "\\": out_str = {out_str, "\\\\"};
        8'h0A: out_str = {out_str, "\\n"};
        8'h0D: out_str = {out_str, "\\r"};
        8'h09: out_str = {out_str, "\\t"};
        default: out_str = {out_str, string'(c)};
      endcase
    end
    return out_str;
  endfunction

  function automatic string dv_env_manifest_json_str(string s);
    return {"\"", dv_env_manifest_json_escape(s), "\""};
  endfunction

  // Writes the vip_config dump JSON (env_manifest.py's own
  // parse_vip_config_dump() reads exactly this shape -- see that
  // function's docstring) to `out_path`. A no-op-but-still-real empty
  // "vip_instances": [] array is written when the registry is empty
  // (nothing registered this run) -- env_manifest.py reports that
  // honestly rather than treating an empty file as NOT_AVAILABLE, since
  // the file genuinely was produced by a real run.
  function automatic void dv_env_manifest_write_vip_config_dump(string out_path);
    int fd;
    string body;
    fd = $fopen(out_path, "w");
    if (fd == 0) begin
      `uvm_error("DV_ENV_MANIFEST", $sformatf("could not open %s for write", out_path))
      return;
    end
    body = "{\n  \"schema_version\": \"1.0\",\n  \"vip_instances\": [\n";
    for (int i = 0; i < dv_env_manifest_vip_registry.size(); i++) begin
      dv_env_manifest_vip_entry e = dv_env_manifest_vip_registry[i];
      string fields_body;
      fields_body = "";
      for (int j = 0; j < e.field_names.size(); j++) begin
        fields_body = {fields_body, "      ", dv_env_manifest_json_str(e.field_names[j]),
                       ": ", dv_env_manifest_json_str(e.field_values[j]),
                       (j == e.field_names.size() - 1) ? "\n" : ",\n"};
      end
      body = {body, "    {\n",
              "      \"instance_path\": ", dv_env_manifest_json_str(e.instance_path), ",\n",
              "      \"vip_type\": ", dv_env_manifest_json_str(e.vip_type), ",\n",
              "      \"config_fields\": {\n", fields_body, "      }\n",
              "    }", (i == dv_env_manifest_vip_registry.size() - 1) ? "\n" : ",\n"};
    end
    body = {body, "  ]\n}\n"};
    $fwrite(fd, "%s", body);
    $fclose(fd);
    `uvm_info("DV_ENV_MANIFEST", $sformatf("wrote vip_config dump (%0d VIP instance(s)) to %s",
                                            dv_env_manifest_vip_registry.size(), out_path), UVM_LOW)
  endfunction

  // ---- env_topology.component_hierarchy: walk + dump -----------------

  // Recursively walks `comp`'s real children (uvm_component::get_children(),
  // stable UVM 1.2 API) and appends one JSON object literal per component
  // (including `comp` itself) to `body_q`. Active/passive is read via
  // uvm_agent::get_is_active() when `comp` really is a uvm_agent (checked
  // with $cast, never guessed from the component's name) -- an agent
  // asking whether a component is active or passive reads this field
  // instead of guessing from an instance name, matching env.manifest.json's
  // own design intent for this layer.
  function automatic void dv_env_manifest_walk_topology(uvm_component comp, ref string body_q[$]);
    uvm_component children[$];
    uvm_agent as_agent;
    string is_active_str;
    is_active_str = "NOT_APPLICABLE";
    if ($cast(as_agent, comp)) begin
      is_active_str = (as_agent.get_is_active() == UVM_ACTIVE) ? "UVM_ACTIVE" : "UVM_PASSIVE";
    end
    body_q.push_back({"    {\n",
      "      \"full_name\": ", dv_env_manifest_json_str(comp.get_full_name()), ",\n",
      "      \"type_name\": ", dv_env_manifest_json_str(comp.get_type_name()), ",\n",
      "      \"is_active\": ", dv_env_manifest_json_str(is_active_str), "\n",
      "    }"});
    comp.get_children(children);
    foreach (children[i]) begin
      dv_env_manifest_walk_topology(children[i], body_q);
    end
  endfunction

  // Writes the env_topology.component_hierarchy dump JSON (env_manifest.py's
  // own parse_topology_dump() reads exactly this shape) to `out_path`,
  // rooted at `top` (pass uvm_top itself -- the real live component tree
  // at end_of_elaboration_phase, not a re-derived or assumed one).
  function automatic void dv_env_manifest_write_topology_dump(uvm_component top, string out_path);
    int fd;
    string body_q[$];
    string body;
    fd = $fopen(out_path, "w");
    if (fd == 0) begin
      `uvm_error("DV_ENV_MANIFEST", $sformatf("could not open %s for write", out_path))
      return;
    end
    dv_env_manifest_walk_topology(top, body_q);
    body = "{\n  \"schema_version\": \"1.0\",\n  \"components\": [\n";
    foreach (body_q[i]) begin
      body = {body, body_q[i], (i == body_q.size() - 1) ? "\n" : ",\n"};
    end
    body = {body, "  ]\n}\n"};
    $fwrite(fd, "%s", body);
    $fclose(fd);
    `uvm_info("DV_ENV_MANIFEST", $sformatf("wrote component_hierarchy dump (%0d component(s)) to %s",
                                            body_q.size(), out_path), UVM_LOW)
  endfunction

  // ---- base test: wires both dumps + the real print_topology() -------

  // A generated environment's own base_test may extend this directly, or
  // simply call the two functions above (plus uvm_top.print_topology())
  // from its own end_of_elaboration_phase if it cannot change its base
  // class -- both are equally real, this class exists only for
  // convenience. Output paths are read from plusargs so no path is ever
  // hardcoded into a generated environment's source: a run that does not
  // pass the plusarg simply does not produce that dump (env_manifest.py
  // then reports that layer NOT_AVAILABLE, honestly, rather than this
  // class silently writing to some default location no caller asked for).
  class dv_env_manifest_base_test extends uvm_test;
    `uvm_component_utils(dv_env_manifest_base_test)

    function new(string name = "dv_env_manifest_base_test", uvm_component parent = null);
      super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
      string vip_dump_path, topo_dump_path;
      super.end_of_elaboration_phase(phase);
      // Real, human-readable topology table in the sim log -- the literal
      // mechanism env.manifest.json's design names -- always runs
      // regardless of plusargs, since it is free (report-server output,
      // not a file this code manages).
      uvm_top.print_topology();
      if ($value$plusargs("VIP_CONFIG_DUMP_PATH=%s", vip_dump_path)) begin
        dv_env_manifest_write_vip_config_dump(vip_dump_path);
      end
      if ($value$plusargs("ENV_TOPOLOGY_DUMP_PATH=%s", topo_dump_path)) begin
        dv_env_manifest_write_topology_dump(uvm_top, topo_dump_path);
      end
    endfunction
  endclass

endpackage : dv_env_manifest_pkg
