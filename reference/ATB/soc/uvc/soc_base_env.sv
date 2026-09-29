/**
 * Abstract: 
 * Class soc_base_env is extended from uvm_env base class.  It implements
 * the build phase to construct the structural elements of this environment.
 */

`ifndef GUARD_SOC_BASE_ENV_SV
`define GUARD_SOC_BASE_ENV_SV

`include "soc_seq_libs.sv"

class soc_base_env extends uvm_env;

  /** UVM Component Utility macro */
  `uvm_component_utils(soc_base_env)

  svt_axi_system_env axi_sys_env[$];
  svt_ahb_system_env ahb_sys_env[$];
  svt_apb_system_env apb_sys_env[$];


  /** VC SOC Virtual Sequencer */
  soc_virtual_sequencer vsqr;

  /** Class Constructor */
  function new(string name="soc_base_env", uvm_component parent=null);
    super.new(name, parent);
  endfunction : new

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
      foreach (apb_sys_env[i]) begin  
        foreach (apb_sys_env[i].slave[j]) begin   
          apb_sys_env[i].slave[j].monitor.checks.disable_check(apb_sys_env[i].slave[j].monitor.checks.pstrb_low_for_read);
          apb_sys_env[i].slave[j].monitor.checks.disable_check(apb_sys_env[i].slave[j].monitor.checks.initial_bus_state_after_reset);
          apb_sys_env[i].slave[j].monitor.checks.disable_check(apb_sys_env[i].slave[j].monitor.checks.psel_match_with_address_map);
        end    
      end             
  endfunction: end_of_elaboration_phase

  //-------------------------------------------------------------------------------
  // For DE local APB Tasks
  //-------------------------------------------------------------------------------
  task CPUWRITE1B(bit [31:0] waddr, bit[31:0] wdata, int wsize=1, string mst_agt="bd_apb_m_ss_cpu");

    cust_apb_master_directed_sequence wr_seq;	
 
    wr_seq = cust_apb_master_directed_sequence::type_id::create("wr_seq");

	void'(wr_seq.randomize() with {
	                                 tran_type == svt_apb_transaction::WRITE;
                                     tran_addr == {waddr[31:2], 2'b00};
									 if (wsize == 1) {
									   tran_pstrb == 1'b1 << waddr[1:0];
									   tran_data  == wdata[7:0] << (waddr[1:0]*8);
									 } else if (wsize == 2) {
									     tran_pstrb == (waddr[1] ? 4'b1100: 4'b0011);
                                         tran_data  == wdata[15:0] << (waddr[1]*16);
									 } else {
									     tran_pstrb == 4'b1111;
                                         tran_data  == wdata;
									 } 
                                   });

    if (vsqr.apb_m_sqr.exists(mst_agt)) begin
       wr_seq.start(vsqr.apb_m_sqr[mst_agt]); 
       `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, vsqr.apb_m_sqr[mst_agt].get_type_name()), UVM_HIGH)
    end	
    else
      `uvm_fatal("ASSERT_APB_Master", $sformatf("Master Agent [%0s] is not existing.. Please check it...", mst_agt))
     
   `uvm_info({mst_agt,":WRITE"}, $sformatf("ADDR[%0h] = %0h  STRB:%0b  SIZE:%d", wr_seq.tran_addr, wr_seq.tran_data, wr_seq.tran_pstrb, wsize), UVM_HIGH)
						  
  endtask


  task CPUWRITE2B(bit [31:0] waddr, bit[31:0] wdata, int wsize=2, string mst_agt="bd_apb_m_ss_cpu");

    cust_apb_master_directed_sequence wr_seq;	
 
    wr_seq = cust_apb_master_directed_sequence::type_id::create("wr_seq");

	void'(wr_seq.randomize() with {
	                                 tran_type == svt_apb_transaction::WRITE;
                                     tran_addr == {waddr[31:2], 2'b00};
									 if (wsize == 1) {
									   tran_pstrb == 1'b1 << waddr[1:0];
									   tran_data  == wdata[7:0] << (waddr[1:0]*8);
									 } else if (wsize == 2) {
									     tran_pstrb == (waddr[1] ? 4'b1100: 4'b0011);
                                         tran_data  == wdata[15:0] << (waddr[1]*16);
									 } else {
									     tran_pstrb == 4'b1111;
                                         tran_data  == wdata;
									 } 
                                   });

    if (vsqr.apb_m_sqr.exists(mst_agt)) begin
       wr_seq.start(vsqr.apb_m_sqr[mst_agt]); 
       `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, vsqr.apb_m_sqr[mst_agt].get_type_name()), UVM_HIGH)
    end	
    else
      `uvm_fatal("ASSERT_APB_Master", $sformatf("Master Agent [%0s] is not existing.. Please check it...", mst_agt))
     
   `uvm_info({mst_agt,":WRITE"}, $sformatf("ADDR[%0h] = %0h  STRB:%0b  SIZE:%d", wr_seq.tran_addr, wr_seq.tran_data, wr_seq.tran_pstrb, wsize), UVM_HIGH)
						  
  endtask
  
  task CPUWRITE4B(bit [31:0] waddr, bit[31:0] wdata, int wsize=4, string mst_agt="bd_apb_m_ss_cpu");

    cust_apb_master_directed_sequence wr_seq;	
 
    wr_seq = cust_apb_master_directed_sequence::type_id::create("wr_seq");

	void'(wr_seq.randomize() with {
	                                 tran_type == svt_apb_transaction::WRITE;
                                     tran_addr == {waddr[31:2], 2'b00};
									 if (wsize == 1) {
									   tran_pstrb == 1'b1 << waddr[1:0];
									   tran_data  == wdata[7:0] << (waddr[1:0]*8);
									 } else if (wsize == 2) {
									     tran_pstrb == (waddr[1] ? 4'b1100: 4'b0011);
                                         tran_data  == wdata[15:0] << (waddr[1]*16);
									 } else {
									     tran_pstrb == 4'b1111;
                                         tran_data  == wdata;
									 } 
                                   });

    if (vsqr.apb_m_sqr.exists(mst_agt)) begin
       wr_seq.start(vsqr.apb_m_sqr[mst_agt]); 
       `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, vsqr.apb_m_sqr[mst_agt].get_type_name()), UVM_HIGH)
    end	
    else
      `uvm_fatal("ASSERT_APB_Master", $sformatf("Master Agent [%0s] is not existing.. Please check it...", mst_agt))
     
   `uvm_info({mst_agt,":WRITE"}, $sformatf("ADDR[%0h] = %0h  STRB:%0b  SIZE:%d", wr_seq.tran_addr, wr_seq.tran_data, wr_seq.tran_pstrb, wsize), UVM_HIGH)
						  
  endtask

  task CPUREAD1B (input bit [31:0] raddr, output bit[31:0] rdata, input int rsize =1, string mst_agt="bd_apb_m_ss_cpu");

    cust_apb_master_directed_sequence rd_seq;	
 
    rd_seq = cust_apb_master_directed_sequence::type_id::create("rd_seq");

	void'(rd_seq.randomize() with {
	                                 tran_type == svt_apb_transaction::READ;
                                     tran_addr == {raddr[31:2], 2'b00};
                                   });
     
    if (vsqr.apb_m_sqr.exists(mst_agt)) begin
      rd_seq.start(vsqr.apb_m_sqr[mst_agt]); 
      `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, vsqr.apb_m_sqr[mst_agt].get_type_name()), UVM_HIGH)	
    end		
    else
      `uvm_fatal("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] is not existing.. Please check it...", mst_agt))

    case(rsize)
      1:
	    rdata = rd_seq.tran_data[raddr[1:0]*8 +: 8];  
	  2:
	    rdata = rd_seq.tran_data[raddr[1]*16 +: 16];
	  default: rdata = rd_seq.tran_data;
	endcase	

   `uvm_info({mst_agt,":READ"}, $sformatf("ADDR[%0h] = %0h SIZE:%0d", rd_seq.tran_addr, rdata, rsize), UVM_HIGH)
						  
  endtask 
  
  task CPUREAD2B (input bit [31:0] raddr, output bit[31:0] rdata, input int rsize =2, string mst_agt="bd_apb_m_ss_cpu");

    cust_apb_master_directed_sequence rd_seq;	
 
    rd_seq = cust_apb_master_directed_sequence::type_id::create("rd_seq");

	void'(rd_seq.randomize() with {
	                                 tran_type == svt_apb_transaction::READ;
                                     tran_addr == {raddr[31:2], 2'b00};
                                   });
     
    if (vsqr.apb_m_sqr.exists(mst_agt)) begin
      rd_seq.start(vsqr.apb_m_sqr[mst_agt]); 
      `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, vsqr.apb_m_sqr[mst_agt].get_type_name()), UVM_HIGH)	
    end		
    else
      `uvm_fatal("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] is not existing.. Please check it...", mst_agt))

    case(rsize)
      1:
	    rdata = rd_seq.tran_data[raddr[1:0]*8 +: 8];  
	  2:
	    rdata = rd_seq.tran_data[raddr[1]*16 +: 16];
	  default: rdata = rd_seq.tran_data;
	endcase	

   `uvm_info({mst_agt,":READ"}, $sformatf("ADDR[%0h] = %0h SIZE:%0d", rd_seq.tran_addr, rdata, rsize), UVM_HIGH)
						  
  endtask 
  
  task CPUREAD4B (input bit [31:0] raddr, output bit[31:0] rdata, input int rsize =4, string mst_agt="bd_apb_m_ss_cpu");

    cust_apb_master_directed_sequence rd_seq;	
 
    rd_seq = cust_apb_master_directed_sequence::type_id::create("rd_seq");

	void'(rd_seq.randomize() with {
	                                 tran_type == svt_apb_transaction::READ;
                                     tran_addr == {raddr[31:2], 2'b00};
                                   });
     
    if (vsqr.apb_m_sqr.exists(mst_agt)) begin
      rd_seq.start(vsqr.apb_m_sqr[mst_agt]); 
      `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, vsqr.apb_m_sqr[mst_agt].get_type_name()), UVM_HIGH)	
    end		
    else
      `uvm_fatal("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] is not existing.. Please check it...", mst_agt))

    case(rsize)
      1:
	    rdata = rd_seq.tran_data[raddr[1:0]*8 +: 8];  
	  2:
	    rdata = rd_seq.tran_data[raddr[1]*16 +: 16];
	  default: rdata = rd_seq.tran_data;
	endcase	

   `uvm_info({mst_agt,":READ"}, $sformatf("ADDR[%0h] = %0h SIZE:%0d", rd_seq.tran_addr, rdata, rsize), UVM_HIGH)
						  
  endtask 
  
  
endclass: soc_base_env

`endif // GUARD_SOC_BASE_ENV_SV

