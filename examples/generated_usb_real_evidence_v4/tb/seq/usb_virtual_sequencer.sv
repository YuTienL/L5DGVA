class usb_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils(usb_virtual_sequencer)
  uvm_sequencer_base seqr_0;
  uvm_sequencer_base seqr_1;
  uvm_sequencer_base seqr_2;
  function new(string name="usb_virtual_sequencer", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
