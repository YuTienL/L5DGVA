
module coretop_reset_generator#(duration=10, initial_value=0)(input bit clock, output bit reset);

  initial begin
    reset = initial_value;
    repeat(duration) @(posedge clock);
    reset = ~reset;
  end

endmodule
