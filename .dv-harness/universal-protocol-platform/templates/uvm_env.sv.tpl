class {{ENV_CLASS}} extends uvm_env;
  `uvm_component_utils({{ENV_CLASS}})
  {{AGENT_DECLS}}
  {{SCOREBOARD_DECL}}
  {{COVERAGE_DECL}}
  function new(string name="{{ENV_CLASS}}", uvm_component parent=null);
    super.new(name,parent);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    {{BUILD_BODY}}
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    {{CONNECT_BODY}}
  endfunction
endclass
