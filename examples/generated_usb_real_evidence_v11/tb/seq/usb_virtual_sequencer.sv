class usb_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils(usb_virtual_sequencer)
  svt_usb_transfer_sequencer usb_xfer_seqr[2];
  svt_usb_system_virtual_sequencer usb_sys_seqr[2];
  svt_apb_master_sequencer apb_seqr;
  svt_axi_master_sequencer axi_seqr;
  usb_reg_sequencer reg_seqr;
  function new(string name="usb_virtual_sequencer", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
