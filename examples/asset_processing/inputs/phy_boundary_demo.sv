// SYNTHETIC WORKED EXAMPLE RTL for the asset-processing table's row 2
// ("PHY model -> phy_boundary.json -> bind-location decision").
//
// Not any real project's RTL. Written deliberately as minimal, obviously
// synthetic source so dv_harness/phy_boundary.py can be exercised end to end
// without a confidential design entering this repo, per CLAUDE.md's Evidence
// Truth Rule and No Golden-Reference Content Mining rule.
//
// Two contrasting boundaries are demonstrated, because the bind decision
// differs between them:
//
//   demo_usb_phy <-> demo_usb_controller  =>  PARALLEL, bindable.
//     The PHY's serial lanes (txp/txn/rxp/rxn) go to the PADS, not to the
//     controller, so they are not part of the shared PHY<->controller port
//     set at all. What the two modules actually share is the 32-bit PIPE
//     symbol interface, which is where transactions are observable. This is
//     the normal, healthy case.
//
//   demo_analog_phy <-> demo_serdes_controller  =>  SERIAL, NOT bindable.
//     These two share only differential lanes. A protocol monitor bound
//     there decodes nothing without a PHY model: it would pass Gate 1
//     (elaborates) and Gate 2 (clock toggles, reset deasserts, no X at t0)
//     and only fail at Gate 3 as a silent monitor. phy_boundary.py reports
//     it as not bindable up front instead of emitting that bind.

module demo_usb_phy (
  input  logic        pclk,
  input  logic        preset_n,

  // Serial pin-side boundary: differential lanes, 1 bit per wire.
  output logic        txp,
  output logic        txn,
  input  logic        rxp,
  input  logic        rxn,

  // Parallel controller-facing boundary: PIPE-style symbol interface.
  input  logic [31:0] pipe_txdata,
  input  logic [3:0]  pipe_txdatak,
  output logic [31:0] pipe_rxdata,
  output logic [3:0]  pipe_rxdatak,
  output logic        pipe_rxvalid,
  input  logic [1:0]  pipe_powerdown
);
endmodule

module demo_usb_controller (
  input  logic        pclk,
  input  logic        preset_n,

  // Controller side of the same parallel boundary. Directions are opposed to
  // the PHY's, which is what phy_boundary.py records as direction_opposed.
  output logic [31:0] pipe_txdata,
  output logic [3:0]  pipe_txdatak,
  input  logic [31:0] pipe_rxdata,
  input  logic [3:0]  pipe_rxdatak,
  input  logic        pipe_rxvalid,
  output logic [1:0]  pipe_powerdown,

  // Application-side bus, not part of the PHY boundary at all.
  input  logic [63:0] app_wdata,
  output logic [63:0] app_rdata
);
endmodule

// The contrasting SERIAL-only boundary: an analog PHY whose only connection
// to its controller is a differential lane pair. No parallel symbol interface
// exists between them, so there is nowhere a protocol monitor could usefully
// bind.

module demo_analog_phy (
  input  logic refclk,
  input  logic por_n,

  output logic serial_txp,
  output logic serial_txn,
  input  logic serial_rxp,
  input  logic serial_rxn
);
endmodule

module demo_serdes_controller (
  input  logic refclk,
  input  logic por_n,

  input  logic serial_txp,
  input  logic serial_txn,
  output logic serial_rxp,
  output logic serial_rxn
);
endmodule
