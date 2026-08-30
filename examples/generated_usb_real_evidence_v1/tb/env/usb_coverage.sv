class usb_coverage extends uvm_component;
  `uvm_component_utils(usb_coverage)
  // COVER: {"TODO": "no real coverage-point evidence gathered this pass; would need to read usb_shared_cfg.sv / a coverage_group file under VIP/src for real bin definitions before filling this in honestly"}
  function new(string name="usb_coverage", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
