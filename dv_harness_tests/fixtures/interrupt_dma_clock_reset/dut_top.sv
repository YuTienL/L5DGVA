// Synthetic fixture RTL for dv_harness_tests/test_interrupt_dma_clock_reset_extraction.py.
// Not any real DUT -- exercises interrupt port naming, a DMA channel-count
// parameter, a DMA descriptor typedef, and both an async and a sync reset
// idiom in one small module.
module dut_top #(
    parameter NUM_DMA_CHANNELS = 4
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cfg_clk,
    input  wire        cfg_rst,
    input  wire        irq_uart,      // UART interrupt
    input  wire  [3:0] irq_vec,       // vectored peripheral interrupts
    output wire        dma_req,
    output wire        dma_ack
);

    typedef struct packed {
        logic [31:0] src_addr;
        logic [31:0] dst_addr;
        logic [15:0] length;
        logic        valid;
    } dma_desc_t;

    logic [1:0] state;
    logic [1:0] next_state;
    logic [7:0] cfg_reg;
    logic [7:0] cfg_reg_next;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 2'b00;
        end else begin
            state <= next_state;
        end
    end

    always @(posedge cfg_clk) begin
        if (cfg_rst) begin
            cfg_reg <= 8'h00;
        end else begin
            cfg_reg <= cfg_reg_next;
        end
    end

endmodule
