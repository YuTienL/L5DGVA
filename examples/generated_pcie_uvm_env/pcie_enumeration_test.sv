class pcie_enumeration_test extends pcie_base_test;
  `uvm_component_utils(pcie_enumeration_test)
  function new(string name="pcie_enumeration_test", uvm_component parent=null); super.new(name,parent); endfunction
  task run_phase(uvm_phase phase);
    pcie_base_vseq vseq;
    phase.raise_objection(this);
    vseq=pcie_base_vseq::type_id::create("vseq");
    vseq.start(env.vseqr);
    phase.drop_objection(this);
  endtask
endclass
