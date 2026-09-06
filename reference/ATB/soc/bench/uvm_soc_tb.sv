/**
 * Abstract:
 * Top-level SystemVerilog testbench does the following:
 * + Includes the VIP packages
 * + Includes each test and initiates the UVM run flow
 */

`timescale 1ns/10ps

`define HDL_TBench sysq062
`define UVM_TBench u_uvm_soc_tb
`define UVM_TBench_HIR `HDL_TBench.`UVM_TBench

`define GMODEL  sysq062.u_modq062.u_gmodel
`define MODEL   sysq062.u_modq062

// Include SOC Bus Configuration  
`include "soc_define_coarse.svi"
`include "coretop_define.svi"

//`include "audtop_define.svi"
//`include "fmtop_define.svi"
//`include "peritop_define.svi"
//`include "hsmtop_define.svi"
//`include "ss_cdec_define.svi"
//`include "ss_cmp_define.svi"
//`include "ss_con_define.svi"
//`include "ss_cpu_define.svi"
//`include "ss_vis_define.svi"
//`include "ss_sf_define.svi"
//`include "ss_vout_define.svi"

`include "soc_define_fine.svi"

// Include the VIP packages

`include "svt_amba.uvm.pkg"
//`include "svt_axi.uvm.pkg"
//`include "svt_ahb.uvm.pkg"
//`include "svt_apb.uvm.pkg"

// Import the VIP packages
import uvm_pkg::*;
import svt_uvm_pkg::*;
import svt_amba_uvm_pkg::*;
//import svt_axi_uvm_pkg::*;
//import svt_ahb_uvm_pkg::*;
//import svt_apb_uvm_pkg::*;

`ifdef BD_USED  
  `include "coretop_dut_wrapper.sv"
`endif
`ifdef AUDTOP_USED  
  `include "audtop_dut_wrapper.sv"
`endif
`ifdef FMTOP_USED  
  `include "fmtop_dut_wrapper.sv"
`endif
`ifdef PERITOP_USED  
  `include "peritop_dut_wrapper.sv"
`endif
`ifdef HSMTOP_USED  
  `include "hsmtop_dut_wrapper.sv"
`endif
`ifdef SS_CDEC_USED  
  `include "ss_cdec_dut_wrapper.sv"
`endif
`ifdef SS_CMP_USED  
  `include "ss_cmp_dut_wrapper.sv"
`endif
`ifdef SS_CON_USED  
  `include "ss_con_dut_wrapper.sv"
`endif
`ifdef SS_CPU_USED  
  `include "ss_cpu_dut_wrapper.sv"
`endif
`ifdef SS_VIS_USED  
  `include "ss_vis_dut_wrapper.sv"
`endif
`ifdef SS_SF_USED  
  `include "ss_sf_dut_wrapper.sv"
`endif
`ifdef SS_VOUT_USED  
  `include "ss_vout_dut_wrapper.sv"
`endif

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

module uvm_soc_tb;

  /** Include DUT Wrapper */ 
`ifdef BD_USED  
   coretop_dut_wrapper u_coretop_dut_wrapper();
`endif
`ifdef AUDTOP_USED  
   audtop_dut_wrapper u_audtop_dut_wrapper();
`endif
`ifdef FMTOP_USED  
   fmtop_dut_wrapper u_fmtop_dut_wrapper();
`endif
`ifdef PERITOP_USED  
   peritop_dut_wrapper u_peritop_dut_wrapper();
`endif
`ifdef HSMTOP_USED  
   hsmtop_dut_wrapper u_hsmtop_dut_wrapper();
`endif
`ifdef SS_CDEC_USED  
   ss_cdec_dut_wrapper u_ss_cdec_dut_wrapper();
`endif
`ifdef SS_CMP_USED  
   ss_cmp_dut_wrapper u_ss_cmp_dut_wrapper();
`endif
`ifdef SS_CON_USED  
   ss_con_dut_wrapper u_ss_con_dut_wrapper();
`endif
`ifdef SS_CPU_USED  
   ss_cpu_dut_wrapper u_ss_cpu_dut_wrapper();
`endif
`ifdef SS_VIS_USED  
   ss_vis_dut_wrapper u_ss_vis_dut_wrapper();
`endif
`ifdef SS_SF_USED  
   ss_sf_dut_wrapper u_ss_sf_dut_wrapper();
`endif
`ifdef SS_VOUT_USED  
   ss_sf_dut_wrapper u_ss_sf_dut_wrapper();
`endif

  /** Include all test files */ 
  `include "soc_test_libs.sv"
   
   soc_base_env  base_env_h;

  // -----------------------------------------------------------------------------
  // UVM phase initiator
  // -----------------------------------------------------------------------------
  initial begin      
	$timeformat(-9, 2, " ns");
    run_test();
  end

  initial begin
    #0.1;
    if (!uvm_config_db#(soc_base_env)::get(null,"env_access","env_handle",base_env_h)) begin
      $fatal("Failed to get soc_base_env handle via config_db");   
    end    
  end

  initial begin
    forever  
      #10us $display("[SIM_TIME=%0t]", $realtime);
  end

  // -----------------------------------------------------------------------------
  // Optionally dump the simulation signals for waveform display
  // -----------------------------------------------------------------------------
`ifdef DUMP_FSDB
  initial begin
    $fsdbDumpfile("uvm_soc_sim");
    $fsdbDumpvars;
  end
`endif	  

endmodule
