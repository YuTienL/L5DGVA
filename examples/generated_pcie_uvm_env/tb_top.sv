module tb_top;
  import uvm_pkg::*;
  import pcie_env_pkg::*;
  logic refclk;
  logic perst_n;
  initial begin refclk=0; forever #5 refclk=~refclk; end
  initial begin perst_n=0; #100; perst_n=1; end
  // Bind DUT and VIP interfaces from environment_manifest.json/current evidence.
  initial run_test();
endmodule
