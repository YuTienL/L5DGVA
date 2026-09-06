
module coretop_clock_generator#(real cycle=50, initial_value=0)(output bit clock);

  initial begin
    clock = initial_value;
    forever begin
      #(cycle/2)
      clock = ~clock;
    end
  end

endmodule
