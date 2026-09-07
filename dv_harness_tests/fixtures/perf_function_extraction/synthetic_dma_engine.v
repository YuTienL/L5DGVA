// Synthetic test fixture for dv_harness_tests/test_perf_function_extraction.py.
// This is NOT a real DUT and describes no real IP -- it exists only to give
// perf_function_extraction.py's line-scan real, cited text to extract from.

module synthetic_dma_engine (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0]  num_beats,
    output wire [31:0]  status
);

    // throughput_mbps = (num_beats * DATA_WIDTH_BYTES) / cycles_elapsed;
    // bandwidth_bps = data_width_bytes * clk_freq_hz;
    // This block computes latency as the number of cycles from request issue to first response beat.
    // Occupancy is measured as busy_cycles / total_cycles.
    // iops = requests_completed / elapsed_seconds;

    // TODO: add a throughput counter here for debug visibility.
    // count = a + b;

endmodule
