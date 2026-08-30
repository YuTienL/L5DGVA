class {{COV_CLASS}} extends uvm_subscriber #(uvm_sequence_item);
  `uvm_component_utils({{COV_CLASS}})
  function new(string name="{{COV_CLASS}}", uvm_component parent=null);
    super.new(name,parent);
  endfunction
  function void write(uvm_sequence_item t);
    // Generated protocol-specific sampling hooks go here.
  endfunction
endclass
