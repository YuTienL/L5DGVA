class usb_connect_test extends usb_base_test;
  `uvm_component_utils(usb_connect_test)
  function new(string name="usb_connect_test", uvm_component parent=null); super.new(name,parent); endfunction
  task run_phase(uvm_phase phase);
    usb_base_vseq vseq;
    phase.raise_objection(this);
    vseq=usb_base_vseq::type_id::create("vseq");
    vseq.start(env.vseqr);
    phase.drop_objection(this);
  endtask
endclass
