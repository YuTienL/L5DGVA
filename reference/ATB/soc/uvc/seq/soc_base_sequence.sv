
/**
 * Abstract:
*/

`ifndef GUARD_SOC_BASE_SEQUENCE_SV
`define GUARD_SOC_BASE_SEQUENCE_SV

class soc_base_sequence extends uvm_sequence;
  
  /** UVM Object Utility macro */
  `uvm_object_utils(soc_base_sequence)

  /** Declare svt_amba_system_sequencer as parent sequencer */
  `uvm_declare_p_sequencer(soc_virtual_sequencer)
  
  /** Class Constructor */
  function new (string name = "soc_base_sequence");
    super.new(name);
  endfunction : new

  //----------------------------------------
  //soc : Slave Service Tasks
  //----------------------------------------
  task ASSERT_SLAVE(string slv_seq_str, string slv_agt);

     case(slv_seq_str)
	   //--------------------
	   // APB Slave Sequence
	   //--------------------
	   "cust_apb_slave_random_response_sequence" : 
	       begin
			  cust_apb_slave_random_response_sequence slave_seq;	   
              slave_seq = cust_apb_slave_random_response_sequence::type_id::create("slave_seq");
              void'(slave_seq.randomize());
	          if (p_sequencer.apb_s_sqr.exists(slv_agt)) begin
                slave_seq.start(p_sequencer.apb_s_sqr[slv_agt]);
                `uvm_info("ASSERT_APB_SLAVE", $sformatf("Slave Agent [%0s] Sequencer Type [%0s]", slv_agt, p_sequencer.apb_s_sqr[slv_agt].get_type_name()), UVM_LOW)	
              end		
              else
                `uvm_fatal("ASSERT_APB_SLAVE", $sformatf("Slave Agent [%0s] is not existing.. Please check it...", slv_agt))			  
	       end 
		"cust_apb_slave_mem_sequence" :
		   begin
              cust_apb_slave_memory_sequence  slave_seq;
              slave_seq = cust_apb_slave_memory_sequence::type_id::create("slave_seq");
              void'(slave_seq.randomize());
	          if (p_sequencer.apb_s_sqr.exists(slv_agt)) begin
                slave_seq.start(p_sequencer.apb_s_sqr[slv_agt]);
                `uvm_info("ASSERT_APB_SLAVE", $sformatf("Slave Agent [%0s] Sequencer Type [%0s]", slv_agt, p_sequencer.apb_s_sqr[slv_agt].get_type_name()), UVM_LOW)	
              end		
              else
                `uvm_fatal("ASSERT_APB_SLAVE", $sformatf("Slave Agent [%0s] is not existing.. Please check it...", slv_agt))				  
		   end
	   //--------------------
	   // AHB Slave Sequence
	   //--------------------
	   "cust_ahb_slave_random_response_sequence" : 
	       begin
			  cust_ahb_slave_random_response_sequence slave_seq;	   
              slave_seq = cust_ahb_slave_random_response_sequence::type_id::create("slave_seq");
              void'(slave_seq.randomize());
	          if (p_sequencer.ahb_s_sqr.exists(slv_agt)) begin
                slave_seq.start(p_sequencer.ahb_s_sqr[slv_agt]);
                `uvm_info("ASSERT_AHB_SLAVE", $sformatf("Slave Agent [%0s] Sequencer Type [%0s]", slv_agt, p_sequencer.ahb_s_sqr[slv_agt].get_type_name()), UVM_LOW)	
              end		
              else
                `uvm_fatal("ASSERT_AHB_SLAVE", $sformatf("Slave Agent [%0s] is not existing.. Please check it...", slv_agt))				  
	       end 
	   "cust_ahb_slave_mem_response_sequence" : 
	       begin
              cust_ahb_slave_mem_response_sequence slave_seq;
              slave_seq = cust_ahb_slave_mem_response_sequence::type_id::create("slave_seq");
              void'(slave_seq.randomize());
	          if (p_sequencer.ahb_s_sqr.exists(slv_agt)) begin
                slave_seq.start(p_sequencer.ahb_s_sqr[slv_agt]);
                `uvm_info("ASSERT_AHB_SLAVE", $sformatf("Slave Agent [%0s] Sequencer Type [%0s]", slv_agt, p_sequencer.ahb_s_sqr[slv_agt].get_type_name()), UVM_LOW)	
              end		
              else
                `uvm_fatal("ASSERT_AHB_SLAVE", $sformatf("Slave Agent [%0s] is not existing.. Please check it...", slv_agt))	
	       end 
	   //--------------------
	   // AXI Slave Sequence
	   //--------------------
	   "cust_axi_slave_random_response_sequence" : 
	       begin
			  cust_axi_slave_random_response_sequence slave_seq;	   
              slave_seq = cust_axi_slave_random_response_sequence::type_id::create("slave_seq");
              void'(slave_seq.randomize());
	          if (p_sequencer.axi_s_sqr.exists(slv_agt)) begin
                slave_seq.start(p_sequencer.axi_s_sqr[slv_agt]);
                `uvm_info("ASSERT_AXI_SLAVE", $sformatf("Slave Agent [%0s] Sequencer Type [%0s]", slv_agt, p_sequencer.axi_s_sqr[slv_agt].get_type_name()), UVM_LOW)	
              end		
              else
                `uvm_fatal("ASSERT_AXI_SLAVE", $sformatf("Slave Agent [%0s] is not existing.. Please check it...", slv_agt))	
	       end 
	   "cust_axi_slave_reorder_response_sequence" : 
	       begin
              cust_axi_slave_reorder_response_sequence slave_seq;
              slave_seq = cust_axi_slave_reorder_response_sequence::type_id::create("slave_seq");
              void'(slave_seq.randomize());
	          if (p_sequencer.axi_s_sqr.exists(slv_agt)) begin
                slave_seq.start(p_sequencer.axi_s_sqr[slv_agt]);
                `uvm_info("ASSERT_AXI_SLAVE", $sformatf("Slave Agent [%0s] Sequencer Type [%0s]", slv_agt, p_sequencer.axi_s_sqr[slv_agt].get_type_name()), UVM_LOW)	
              end		
              else
                `uvm_fatal("ASSERT_AXI_SLAVE", $sformatf("Slave Agent [%0s] is not existing.. Please check it...", slv_agt))				  
	       end 
	   "cust_axi_slave_mem_response_sequence" : 
	       begin
              cust_axi_slave_mem_response_sequence slave_seq;
              slave_seq = cust_axi_slave_mem_response_sequence::type_id::create("slave_seq");
              void'(slave_seq.randomize());
	          if (p_sequencer.axi_s_sqr.exists(slv_agt)) begin
                slave_seq.start(p_sequencer.axi_s_sqr[slv_agt]);
                `uvm_info("ASSERT_AXI_SLAVE", $sformatf("Slave Agent [%0s] Sequencer Type [%0s]", slv_agt, p_sequencer.axi_s_sqr[slv_agt].get_type_name()), UVM_LOW)	
              end		
              else
                `uvm_fatal("ASSERT_AXI_SLAVE", $sformatf("Slave Agent [%0s] is not existing.. Please check it...", slv_agt))				  
	       end
		default:
             `uvm_fatal("ASSERT_SLAVE", $sformatf("Slave Sequence [%0s] is not existing.. Please check it...", slv_seq_str))	
     endcase
  endtask	

  //----------------------------------------
  //soc : APB Master Tasks
  //----------------------------------------
  task APB_WRITE(bit [31:0] waddr, bit[31:0] wdata, int wsize =4, string mst_agt);

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

    if (p_sequencer.apb_m_sqr.exists(mst_agt)) begin
       wr_seq.start(p_sequencer.apb_m_sqr[mst_agt]); 
       `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, p_sequencer.apb_m_sqr[mst_agt].get_type_name()), UVM_LOW)
    end	
    else
      `uvm_fatal("ASSERT_APB_Master", $sformatf("Master Agent [%0s] is not existing.. Please check it...", mst_agt))
     
   `uvm_info({mst_agt,":WRITE"}, $sformatf("ADDR[%0h] = %0h  STRB:%0b  SIZE:%d", wr_seq.tran_addr, wr_seq.tran_data, wr_seq.tran_pstrb, wsize), UVM_HIGH)
						  
  endtask

  //-------------------------
  task APB_READ (input bit [31:0] raddr, output bit[31:0] rdata, input int rsize =4, string mst_agt);

    cust_apb_master_directed_sequence rd_seq;	
 
    rd_seq = cust_apb_master_directed_sequence::type_id::create("rd_seq");

	void'(rd_seq.randomize() with {
	                                 tran_type == svt_apb_transaction::READ;
                                     tran_addr == {raddr[31:2], 2'b00};
                                   });
     
    if (p_sequencer.apb_m_sqr.exists(mst_agt)) begin
      rd_seq.start(p_sequencer.apb_m_sqr[mst_agt]); 
      `uvm_info("ASSERT_APB_MASTER", $sformatf("Master Agent [%0s] Sequencer Type [%0s]", mst_agt, p_sequencer.apb_m_sqr[mst_agt].get_type_name()), UVM_LOW)	
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

endclass: soc_base_sequence 

`endif // GUARD_SOC_VIRTUAL_SEQUENCE_SV

