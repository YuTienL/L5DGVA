class {{VSEQ_CLASS}} extends uvm_sequencer;
  `uvm_component_utils({{VSEQ_CLASS}})
  {{SEQUENCER_HANDLES}}
  function new(string name="{{VSEQ_CLASS}}", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
