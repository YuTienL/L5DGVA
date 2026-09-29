// Synthetic fixture RTL whose always block resets on a signal that does NOT
// match the reset naming convention (init_done) -- used as a negative
// control to prove the extractor does not guess a reset from an arbitrary
// first `if` condition.
module ambiguous_dut (
    input  wire clk,
    input  wire init_done
);
    logic [1:0] state;

    always @(posedge clk) begin
        if (init_done) begin
            state <= 2'b01;
        end else begin
            state <= state;
        end
    end
endmodule
