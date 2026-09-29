// Synthetic fixture RTL for dv_harness_tests/test_error_recovery_flow_extraction.py.
// Not any real DUT -- exercises error/fault port naming only.
module err_dut_top (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        crc_error,      // CRC mismatch detected
    input  wire  [1:0] fault_code,     // fault classification code
    output wire        recovery_done
);
endmodule
