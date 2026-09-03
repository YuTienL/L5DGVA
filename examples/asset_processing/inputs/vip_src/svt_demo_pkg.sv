// SYNTHETIC WORKED EXAMPLE "VIP source" for the asset-processing table's
// rows 12 and 13.
//
// This is NOT a real Synopsys VIP and contains no vendor code. It is written
// deliberately to look structurally like one (an svt_-prefixed package of
// config / sequence / driver / monitor classes) so that
// dv_harness/vip_symbol_index.py can be exercised end to end against real
// text, without a licensed VIP source tree ever entering this repo -- which
// CLAUDE.md's context-budget tier 1 (NEVER-VIP-SOURCE) forbids reading in the
// first place, and which this file's whole purpose is to avoid needing.
//
// The method BODIES below matter to the test: the indexer must record every
// declaration and location while retaining none of this implementation text.
// vip_symbol_index.assert_no_bodies_retained() is what proves it.

package svt_demo_pkg;

  class svt_demo_cfg extends uvm_object;
    rand bit          enable_protocol_checks;
    rand int unsigned max_burst_length;
    bit               coverage_enable;
    string            interface_name;

    extern virtual function void set_defaults();

    virtual function void apply_preset(input int preset_id);
      if (preset_id > 0) begin
        max_burst_length = preset_id * 4;
        $display("svt_demo_cfg: applied preset %0d", preset_id);
      end
    endfunction

    virtual task wait_for_ready(input int timeout_ns);
      while (timeout_ns > 0) begin
        #1;
        timeout_ns--;
      end
    endtask
  endclass

  class svt_demo_transaction extends uvm_sequence_item;
    rand bit [31:0] address;
    rand bit [31:0] payload;
    rand bit        is_write;

    virtual function string convert2string();
      return $sformatf("addr=%0h data=%0h", address, payload);
    endfunction
  endclass

  class svt_demo_base_sequence extends uvm_sequence;
    rand int unsigned num_transactions;

    virtual task body();
      repeat (num_transactions) begin
        `uvm_do(req)
      end
    endtask

    virtual task pre_start();
      if (starting_phase != null) begin
        starting_phase.raise_objection(this);
      end
    endtask
  endclass

  virtual class svt_demo_driver extends uvm_driver;
    virtual function void build_phase(uvm_phase phase);
      super.build_phase(phase);
    endfunction

    virtual task run_phase(uvm_phase phase);
      forever begin
        seq_item_port.get_next_item(req);
        seq_item_port.item_done();
      end
    endtask
  endclass

  class svt_demo_monitor extends uvm_monitor;
    bit checks_enable;

    virtual task run_phase(uvm_phase phase);
      forever begin
        @(posedge vif.clk);
      end
    endtask

    virtual function void report_phase(uvm_phase phase);
      `uvm_info("DEMO_MON", "done", UVM_LOW)
    endfunction
  endclass

  class svt_demo_agent extends uvm_agent;
    svt_demo_cfg cfg;

    virtual function void build_phase(uvm_phase phase);
      super.build_phase(phase);
    endfunction
  endclass

endpackage
