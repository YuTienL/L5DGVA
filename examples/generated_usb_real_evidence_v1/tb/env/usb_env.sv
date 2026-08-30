class usb_env extends uvm_env;
  `uvm_component_utils(usb_env)
  usb_config cfg;
  usb_virtual_sequencer vseqr;
  usb_scoreboard sb;
  usb_coverage cov;
  svt_usb_agent usb0_agent__TODO_NOT_YET_ESTABLISHED_IN_PROJECT;

  function new(string name="usb_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(usb_config)::get(this,"","cfg",cfg))
      cfg=usb_config::type_id::create("cfg");
    vseqr=usb_virtual_sequencer::type_id::create("vseqr",this);
    sb=usb_scoreboard::type_id::create("sb",this);
    cov=usb_coverage::type_id::create("cov",this);
    usb0_agent__TODO_NOT_YET_ESTABLISHED_IN_PROJECT=svt_usb_agent::type_id::create("usb0_agent__TODO_NOT_YET_ESTABLISHED_IN_PROJECT",this);
  endfunction
endclass
