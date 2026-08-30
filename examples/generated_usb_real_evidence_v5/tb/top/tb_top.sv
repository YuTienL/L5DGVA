module tb_top;
  import uvm_pkg::*;
  import usb_env_pkg::*;
  logic xtali;
  logic xprstn;
  initial begin xtali=0; forever #5 xtali=~xtali; end
  initial begin xprstn=0; #100; xprstn=1; end
  // Bind DUT and VIP interfaces from environment_manifest.json/current evidence.
  initial run_test();
endmodule
