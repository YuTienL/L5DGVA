/**
 * Abstract:
 * Top-level SystemVerilog testbench does the following:
 * + Includes the VIP packages
 * + Includes each test and initiates the UVM run flow
 */

`define HDL_TBench sysq062
`define UVM_TBench u_uvm_coretop_tb
`define UVM_TBench_HIR `HDL_TBench.`UVM_TBench

`define GMODEL  sysq062.u_modq062.u_gmodel
`define MODEL   sysq062.u_modq062

// Include SOC Bus Configuration  
`include "bd_define_coarse.svi"
//`include "ss_cpu_define.svi"
//`include "ss_con_define.svi"
`include "bd_define_fine.svi"

// Include the VIP packages

`include "svt_axi.uvm.pkg"
`include "svt_ahb.uvm.pkg"
`include "svt_apb.uvm.pkg"

 import uvm_pkg::*;
 import svt_uvm_pkg::*;
 import svt_amba_uvm_pkg::*;
 import svt_axi_uvm_pkg::*;
 import svt_ahb_uvm_pkg::*;
 import svt_apb_uvm_pkg::*;

`ifdef BD_USED  
  `include "coretop_dut_wrapper.sv"
`endif
//`ifdef SS_CPUT_USED
//  `include "ss_cpu_dut_wrapper.sv"
//`endif
//`ifdef SS_CON_USED
//  `include "ss_con_dut_wrapper.sv"
//`endif
 
`ifdef INCLUDE_SVT_AXI_MASTER_BIND_IF
 `include "user_svt_axi_master_bind_if.svi"
`endif 
`ifdef INCLUDE_SVT_AHB_MASTER_BIND_IF
 `include "user_svt_ahb_master_bind_if.svi"
`endif 
`ifdef INCLUDE_SVT_APB_MASTER_BIND_IF
 `include "user_svt_apb_master_bind_if.svi"
`endif 
`ifdef INCLUDE_SVT_AXI_SLAVE_BIND_IF
 `include "user_svt_axi_slave_bind_if.svi"
`endif  
`ifdef INCLUDE_SVT_AHB_SLAVE_BIND_IF
 `include "user_svt_ahb_slave_bind_if.svi"
`endif  
`ifdef INCLUDE_SVT_APB_SLAVE_BIND_IF
 `include "user_svt_apb_slave_bind_if.svi"
`endif 

`include "dv_utils_uvm.pkg"

 import dv_utils_uvm_pkg::*;

module uvm_coretop_tb;

  /** Include DUT Wrapper */ 
`ifdef BD_USED  
   coretop_dut_wrapper u_coretop_dut_wrapper();
`endif
//`ifdef SS_CPU_USED  
//   ss_cpu_dut_wrapper u_ss_cpu_dut_wrapper();
//`endif
//`ifdef SS_CON_USED  
//   ss_con_dut_wrapper u_ss_con_dut_wrapper();
//`endif
//
  /** Include all test files */ 
  `include "soc_test_libs.sv"

  // -----------------------------------------------------------------------------
  // UVM phase initiator
  // -----------------------------------------------------------------------------
  initial begin
	$timeformat(-9, 2, " ns"); 	 
    uvm_config_db#(virtual svt_axi_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.amba_system_env_0.axi_system[0]", "vif", u_coretop_dut_wrapper.coretop_axi_if_0);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.amba_system_env_0.apb_system[0]", "vif", u_coretop_dut_wrapper.coretop_apb_if_0);
    uvm_config_db#(virtual svt_ahb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.amba_system_env_0.ahb_system[0]", "vif", u_coretop_dut_wrapper.coretop_ahb_if_0);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.amba_system_env_0.apb_system[1]", "vif", u_coretop_dut_wrapper.coretop_apb_if_1);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.amba_system_env_0.apb_system[2]", "vif", u_coretop_dut_wrapper.coretop_apb_if_2);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.amba_system_env_0.apb_system[3]", "vif", u_coretop_dut_wrapper.coretop_apb_if_3);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.amba_system_env_0.apb_system[4]", "vif", u_coretop_dut_wrapper.coretop_apb_if_4);
    run_test();
  end

  initial begin
    forever  
      #500ns $display("[SIM_TIME=%0t]", $realtime);
  end

  // -----------------------------------------------------------------------------
  // Optionally dump the simulation signals for waveform display
  // -----------------------------------------------------------------------------
`ifdef DUMP_FSDB
  initial begin
    $fsdbDumpfile("uvm_coretop_sim");
    $fsdbDumpvars;
  end
`endif	  

endmodule
