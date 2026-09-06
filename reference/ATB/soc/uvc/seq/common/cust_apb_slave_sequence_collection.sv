`ifndef GUARD_CUST_APB_SLAVE_SEQUENCE_COLLECTION_SV
`define GUARD_CUST_APB_SLAVE_SEQUENCE_COLLECTION_SV

// =============================================================================
/**
 * This base sequence obtains the configuration from the sequencer during the
 * pre_body() callback. It does not raise or drop objections because slave
 * sequences are reactive, and so are always running.
 * 
 * Sequencer: Slave agent sequencer
 */
class cust_apb_slave_base_sequence extends svt_sequence #(svt_apb_slave_transaction);
  /** Port Configuration handle set by pre_body. */
   svt_apb_slave_configuration cfg;

  `svt_xvm_object_utils(cust_apb_slave_base_sequence)
  `svt_xvm_declare_p_sequencer(svt_apb_slave_sequencer)

  /** Constructor of base sequence */
  function new(string name="cust_apb_slave_base_sequence");
    super.new(name);
  endfunction

  /** 
   * Routes messages through the parent sequencer and raises an objection and gets
   * the sequencer configuration. 
   */

  virtual task body();
    svt_configuration get_cfg;
    `svt_xvm_debug("body", {"Executing ", (is_item() ? "item " : "sequence "), get_name(), " (", get_type_name(), ")"});
    p_sequencer.get_cfg(get_cfg);
    if (!$cast(cfg, get_cfg)) begin
      `svt_xvm_fatal("body", "Unable to cast the configuration to a svt_apb_slave_configuration class");
    end
  endtask: body

  /** Used to sink the responses from the response queue */
  task sink_responses();
    svt_apb_slave_transaction rsp;
    fork
      begin
        forever begin
          get_response(rsp);
        end
      end
    join_none
  endtask: sink_responses
endclass: cust_apb_slave_base_sequence

/**
 * Abstract:
 * class cust_apb_slave_random_response_sequence defines a sequence class that
 * provides random slave response. The sequence receives a response object of type
 * svt_apb_slave_transaction, from slave sequencer. The sequence class then
 * randomizes the response with constraints and provides it to the slave driver
 * within the slave agent.
 */
class cust_apb_slave_random_response_sequence extends cust_apb_slave_base_sequence;

  /** UVM Object Utility macro */
  `svt_xvm_object_utils(cust_apb_slave_random_response_sequence)

  /** Class Constructor */
  function new(string name="cust_apb_slave_random_response_sequence");
    super.new(name);
  endfunction

  virtual task body();
    bit pslverr_read_data_x;
    bit status_pslverr_read_data_x;
    int rand_insertion;
    `svt_xvm_note("body", "Entered ...");
`ifdef SVT_UVM_TECHNOLOGY
    status_pslverr_read_data_x = uvm_config_db #(bit)::get(null, get_full_name(), "pslverr_read_data_x", pslverr_read_data_x);
`endif
    `svt_xvm_debug("body", $sformatf("pslverr_read_data_x is 'd%0d as a result of %0s.", pslverr_read_data_x, status_pslverr_read_data_x ? "config DB" : "randomization"));

    forever begin
      rand_insertion = $urandom;
      p_sequencer.response_request_port.peek(req);
      if (req.cfg == null) begin
        req.cfg = cfg;
      end

      /** 
       * Demonstration of response randomization with constraints.
       */
      if(pslverr_read_data_x && req.xact_type == svt_apb_transaction::READ) begin
	req.pslverr_enable = $urandom;
	if(req.pslverr_enable)
	  req.read_data_contains_x = 1;
	`svt_xvm_send(req)
      end
      else begin
	req.xact_type.rand_mode(0);
        `svt_xvm_do_with(req,{
	  if(!rand_insertion%20)
	    data == '1;
	})
      end
      `svt_xvm_debug("body", $sformatf("pslverr  ='b%0b",req.pslverr_enable));
    end

    `svt_xvm_note("body", "Exiting...");
  endtask: body

endclass: cust_apb_slave_random_response_sequence

/**
 * This sequence generates memory responses to slave requests.  This sequence
 * gets the slave request from slave sequencer, randomizes the response, and
 * then either updates the internal memory for write transations or updates
 * the transaction with memory data for read transactions.  If the requested
 * address is outside of the configured bounds for the memory then the slave
 * will return with a pslverr response.
 * 
 * This sequence runs forever, and so is not registered with the slave sequence
 * library.
 */
class cust_apb_slave_memory_sequence extends cust_apb_slave_base_sequence;
  
  `svt_xvm_object_utils(cust_apb_slave_memory_sequence)
  `svt_xvm_declare_p_sequencer(svt_apb_slave_sequencer)

  /** Slave memory. */
  svt_apb_memory apb_slave_mem;

  /** Wait cycles weightage. */
  int unsigned zero_wait_cycles_wt;
  int unsigned short_wait_cycles_wt;
  int unsigned long_wait_cycles_wt;

  function new(string name="cust_apb_slave_memory_sequence");
    super.new(name);
  endfunction

  virtual task body();
    // Status bits for config db
    bit status_zero_wait_cycles_wt;
    bit status_short_wait_cycles_wt;
    bit status_long_wait_cycles_wt;

    // Status bit for randomization
    integer status;

    // Container for pstrb value
    bit[`SVT_APB_MAX_DATA_WIDTH/8 -1 :0] byteen;

    // Number of pstrb bits
    int byteen_bits;

    super.body();

`ifdef SVT_UVM_TECHNOLOGY
    status_zero_wait_cycles_wt = uvm_config_db #(int unsigned)::get(m_sequencer,get_type_name(), "zero_wait_cycles_wt", zero_wait_cycles_wt);
    status_short_wait_cycles_wt = uvm_config_db #(int unsigned)::get(m_sequencer,get_type_name(), "short_wait_cycles_wt", short_wait_cycles_wt);
    status_long_wait_cycles_wt = uvm_config_db #(int unsigned)::get(m_sequencer,get_type_name(), "long_wait_cycles_wt", long_wait_cycles_wt);
`else
    status_zero_wait_cycles_wt = m_sequencer.get_config_int({get_type_name(), ".zero_wait_cycles_wt"}, zero_wait_cycles_wt);
    status_short_wait_cycles_wt = m_sequencer.get_config_int({get_type_name(), ".short_wait_cycles_wt"}, short_wait_cycles_wt);
    status_long_wait_cycles_wt = m_sequencer.get_config_int({get_type_name(), ".long_wait_cycles_wt"}, long_wait_cycles_wt);
`endif

    `svt_xvm_debug("body", $sformatf("zero_wait_cycles_wt is 'd%0d as a result of %0s.", zero_wait_cycles_wt, status_zero_wait_cycles_wt ? "config DB" : "default value"));
    `svt_xvm_debug("body", $sformatf("short_wait_cycles_wt is 'd%0d as a result of %0s.", short_wait_cycles_wt, status_short_wait_cycles_wt ? "config DB" : "default value"));
    `svt_xvm_debug("body", $sformatf("long_wait_cycles_wt is 'd%0d as a result of %0s.", long_wait_cycles_wt, status_long_wait_cycles_wt ? "config DB" : "default value"));

    //fork off a thread to pull the responses out of response queue
    sink_responses();

    // Instantiate the slave memory
    create_apb_slave_mem();

    forever begin
      // Gets the request from monitor
      p_sequencer.response_request_port.peek(req);

      // Provide weights to different wait cycles if they are passed from test
      if(status_zero_wait_cycles_wt)
        req.ZERO_WAIT_CYCLES_wt = zero_wait_cycles_wt;
      if(status_short_wait_cycles_wt)
        req.SHORT_WAIT_CYCLES_wt = short_wait_cycles_wt;
      if(status_long_wait_cycles_wt)
        req.LONG_WAIT_CYCLES_wt = long_wait_cycles_wt;
      if (req.cfg == null) begin
        req.cfg = cfg;
      end
      
      if (req.xact_type != svt_apb_transaction::IDLE &&
          !apb_slave_mem.is_in_bounds(req.address)) begin
       // `svt_xvm_warning("body", $sformatf("Attempted %s to paddr='h%0x failed.  Returning pslverr with this transaction.", req.xact_type.name(), req.address));
        `svt_xvm_warning("body", $sformatf("Attempted %0s failed.  Returning pslverr with this transaction.",`SVT_APB_PRINT_PREFIX(req)));
        req.pslverr_enable = 1;
      end
      else begin
        // Turn off rand_mode for the payload since it is retrieved from the memory and
        // then randomize the response.
        req.data.rand_mode(0);
        req.pslverr_enable.rand_mode(0);

        status = req.randomize();
        byteen_bits = req.cfg.sys_cfg.pdata_width/8;

        if(req.cfg.sys_cfg.apb4_enable)  begin
          byteen = req.pstrb;
        end
        else begin
          byteen = ((1<< byteen_bits) -1);
        end
        if(!status)
          `svt_xvm_fatal("body", "Randomization of slave response failed");
        if (!req.pslverr_enable) begin
          // For write transaction, put the write data to memory
          if(req.xact_type == svt_apb_slave_transaction::WRITE) begin
            `svt_xvm_debug("body", $sformatf("Updating slave memory for %0s byteen='h%0x.", `SVT_APB_PRINT_PREFIX(req),byteen));
            void'(apb_slave_mem.write(req.address,req.data,byteen));
          end
          // For Read transaction, get the read data from memory
          else if(req.xact_type == svt_apb_slave_transaction::READ)begin
            req.data = apb_slave_mem.read(req.address);
          `svt_xvm_debug("body", $sformatf("Updating slave memory for %0s byteen='h%0x.", `SVT_APB_PRINT_PREFIX(req),byteen));
`ifdef SVT_APB_SLAVE_DRIVE_X_IF_MEMDATA_X  
            // If the vlaue read from apb_slave_mem contains X, set the following.
            // $isknown(data) can be used, but using this for performance.  
            req.read_data_contains_x = 0;
            if (^(apb_slave_mem.read(req.address)) === 1'bx) begin
              req.read_data_contains_x = 1;
            end
`endif	    
          end
        end
        else begin
          `svt_xvm_debug("body", $sformatf("pslverr issued for this transaction %0s, so the memory was not updated.", `SVT_APB_PRINT_PREFIX(req)));
        end
      end

      // Finally send the response
      `svt_xvm_send(req)
    end
  endtask: body

  virtual function void create_apb_slave_mem();
    svt_apb_slave_agent slave_agent;

    if ($cast(slave_agent, p_sequencer.get_parent())) begin
      if (slave_agent.apb_slave_mem != null) begin
        apb_slave_mem = slave_agent.apb_slave_mem;
      end
      else begin
        apb_slave_mem = new("apb_slave_mem"   ,                // Memory name
                            cfg.sys_cfg.pdata_width,           // Data width
                            0,                                 // Address region
                            0,                                 // Lower address bound
                            ((1<<cfg.sys_cfg.paddr_width)-1)); // Upper address bound
        slave_agent.apb_slave_mem = apb_slave_mem;
      end
    end
    else begin
      `svt_xvm_fatal("create_apb_slave_mem", "This sequence must be run by the sequencer contained by svt_apb_slave_agent.");
    end
  endfunction: create_apb_slave_mem

endclass: cust_apb_slave_memory_sequence

`endif // GUARD_CUST_APB_SLAVE_SEQUENCE_COLLECTION_SV
