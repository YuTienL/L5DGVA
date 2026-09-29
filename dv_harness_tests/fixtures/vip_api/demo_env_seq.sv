// SYNTHETIC generated-sequence fixture for dv_harness/vip_api_card.py
// (spec section 187, VIPApiCard + "unprovable API -> BLOCKED").
//
// This is NOT a real generated environment and NOT any vendor's code. It is
// shaped like what this project's own generator emits (a virtual sequence that
// declares VIP handles and calls VIP APIs on them) and every VIP symbol it
// cites is really declared in
// examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv -- the synthetic
// "VIP source" that vip_symbol_index.py is already exercised against.
//
// The tests MUTATE this clean file one defect at a time, so each assertion
// proves the validator caught that specific injected fabrication.

class demo_env_base_vseq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(demo_env_base_vseq)

  function new(string name = "demo_env_base_vseq");
    super.new(name);
  endfunction

  virtual task body();
    svt_demo_cfg cfg;
    svt_demo_agent agent;
    svt_demo_transaction txn;

    // evidence: svt_demo_pkg.sv:24 -- extern virtual function void set_defaults();
    cfg = new("cfg");
    cfg.set_defaults();
    // evidence: svt_demo_pkg.sv:26 -- virtual function void apply_preset(input int preset_id);
    cfg.apply_preset(2);
    // evidence: svt_demo_pkg.sv:33 -- virtual task wait_for_ready(input int timeout_ns);
    cfg.wait_for_ready(1000);

    // A base-library call on a VIP handle: uvm_object API, not VIP API.
    `uvm_info(get_type_name(), cfg.get_full_name(), UVM_MEDIUM)

    txn = svt_demo_transaction::type_id::create("txn");
    if (!txn.randomize()) begin
      `uvm_fatal("body", "randomization of svt_demo_transaction failed")
    end
    // evidence: svt_demo_pkg.sv:46 -- virtual function string convert2string();
    `uvm_info(get_type_name(), txn.convert2string(), UVM_MEDIUM)
  endtask

endclass
