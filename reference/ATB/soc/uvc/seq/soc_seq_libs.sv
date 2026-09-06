/**
 * Abstract:
*/

`ifndef GUARD_SOC_SEQ_LIBS_SV
`define GUARD_SOC_SEQ_LIBS_SV

`include "cust_ahb_master_sequence_collection.sv"
`include "cust_ahb_slave_sequence_collection.sv"
`include "cust_apb_master_sequence_collection.sv"
`include "cust_apb_slave_sequence_collection.sv"
`include "cust_axi_master_sequence_collection.sv"
`include "cust_axi_slave_sequence_collection.sv"

`include "soc_base_sequence.sv"

class soc_seq_libs extends soc_base_sequence;
  /** UVM Object Utility macro */
  `uvm_object_utils(soc_seq_libs)
  
  //--------------------------
  // Variable definition here
  //-------------------------
  

  /** Class Constructor */
  function new (string name = "soc_seq_libs");
    super.new(name);
  endfunction : new

  //--------------------------------------
  // CORETOP Slave Response Sequence
  //----------------------------------------
  task soc_slave_init_seq();		  
    fork
	  begin	//For AHB Slave	  
        ASSERT_SLAVE("cust_ahb_slave_mem_response_sequence", "bd_ahb_s_fmtop");
      end		 
      begin //For APB Slave
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_audtop");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_dmatop");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_fmtop");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_gtop");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s0_peritop");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s1_peritop");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_hsmtop");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ucie");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ss_cdec");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ss_cmp");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ss_con");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ss_cpu");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ss_vis");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s0_ddr_chip");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s1_ddr_chip");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ss_sf");
        ASSERT_SLAVE("cust_apb_slave_mem_sequence", "bd_apb_s_ss_vout");
	  end
      begin //For AXI Slave
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s_ucie");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s_ss_con");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s_ss_cpu");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s0_ddr_chip");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s1_ddr_chip");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s2_ddr_chip");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s3_ddr_chip");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s4_ddr_chip");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s5_ddr_chip");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s_sram_slave_group");
        ASSERT_SLAVE("cust_axi_slave_mem_response_sequence", "bd_axi_s_ss_sf");
	  end
	join_none
  endtask

  //--------------------------------------
  // CORETOP Initial Sequence 
  //--------------------------------------
  task soc_init_seq();
     APB_WRITE (32'h1001_5900, 8'h02, 1, "bd_apb_m_ss_cpu");   
     APB_WRITE (32'h1001_5910, 8'h02, 1, "bd_apb_m_ss_cpu"); 
     APB_WRITE (32'h1001_5920, 8'h02, 1, "bd_apb_m_ss_cpu");   
     APB_WRITE (32'h1001_59D0, 8'h02, 1, "bd_apb_m_ss_cpu");   
  endtask

  //--------------------------------------
  // Global Initial Sequence
  //--------------------------------------
  task global_init_seq();
	 bit [31:0] rdata;

     //------------------------
	 // User defined tasks
	 //------------------------
     $display("Start to Set Clock Frequency \n");
     APB_WRITE(32'h1000_0323,8'h00,1, "bd_apb_m_peritop");     // SPLL1_PD_LDO,ES1
     APB_WRITE(32'h1000_0343,8'h00,1, "bd_apb_m_hsmtop");     // SPLL2_PD_LDO,ES1
     APB_WRITE(32'h1000_0363,8'h00,1, "bd_apb_m_ss_cpu");     // TGPLL_PD_LDO,ES1
     APB_WRITE(32'h1000_0383,8'h00,1, "bd_apb_m_ss_cpu");     // APLL_PD_LDO,ES1
     APB_WRITE(32'h1000_00A4,8'd09,1, "bd_apb_m_ss_cpu");     // regclk   = 2000/10 MHz
     APB_WRITE(32'h1000_00A5,8'd05,1, "bd_apb_m_ss_cpu");     // romclk   = 2000/6  MHz
     APB_WRITE(32'h1000_00AC,8'd02,1, "bd_apb_m_peritop");     // cpuclk   = 2000/3  MHz
     APB_WRITE(32'h1000_00C6,8'd10,1, "bd_apb_m_peritop");     // mcuclk   = 2000/11 MHz
     APB_WRITE(32'h1000_00C7,8'd09,1, "bd_apb_m_peritop");     // mperclk  = 2000/10 MHz

     APB_READ(32'h1000_00A4, rdata,1, "bd_apb_m_hsmtop");    // regclk   = 2000/10 MHz
     $display("...CPU_RD[%0h]:%0h", 32'h1000_00A4, rdata);	
     APB_READ(32'h1000_00A4, rdata,1, "bd_apb_m_peritop");    // regclk   = 2000/10 MHz
     $display("...MCU_RD[%0h]:%0h", 32'h1000_00A4, rdata);	
     APB_READ(32'h1000_00A4, rdata,1, "bd_apb_m_ss_cpu");     // regclk   = 2000/10 MHz
     $display("...PERI_RD[%0h]:%0h", 32'h1000_00A4, rdata);	

  endtask  

endclass : soc_seq_libs

//--------------------------------------
// Global Initial Sequence
//--------------------------------------


`endif // GUARD_SOC_SEQ_LIBS_SV
