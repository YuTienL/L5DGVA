class pcie_env extends uvm_env;
  `uvm_component_utils(pcie_env)
  pcie_config cfg;
  pcie_virtual_sequencer vseqr;
  pcie_scoreboard sb;
  pcie_coverage cov;
  pcie_vip_agent pcie_vip;

  function new(string name="pcie_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(pcie_config)::get(this,"","cfg",cfg))
      cfg=pcie_config::type_id::create("cfg");
    vseqr=pcie_virtual_sequencer::type_id::create("vseqr",this);
    sb=pcie_scoreboard::type_id::create("sb",this);
    cov=pcie_coverage::type_id::create("cov",this);
    pcie_vip=pcie_vip_agent::type_id::create("pcie_vip",this);
  endfunction
endclass
