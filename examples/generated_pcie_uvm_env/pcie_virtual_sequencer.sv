class pcie_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils(pcie_virtual_sequencer)
  uvm_sequencer_base seqr_0;
  function new(string name="pcie_virtual_sequencer", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
