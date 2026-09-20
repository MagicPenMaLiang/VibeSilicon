// VibeSilicon Module Contract v1
// Module      : <module_name>
// Purpose     : <one sentence hardware purpose>
// Clocks      : <clock name, frequency, relationship>
// Resets      : <reset name, polarity, sync/async assertion and release>
// Interfaces  : <protocol, direction, backpressure and ordering>
// Numeric     : <width, signedness, Q format, rounding, saturation/wrap>
// Latency     : <fixed N cycles | variable min/max and trigger>
// Throughput  : <II or transfers/cycle>
// Invariants  : <protocol, latency, numeric, reset and CDC invariants>
// Generated   : no | <generator, version, source hash>
// Target      : fpga | asic | portable (record target-specific wrapper separately)
// Source      : handwritten | generated (record regeneration evidence if generated)

`default_nettype none

module <module_name> (
    input logic <clock_name>_clk_i,
    input logic <reset_name>_rst_ni
);

    // Implementation.

endmodule

`default_nettype wire
