// VibeSilicon Module Contract v1
// Module      : counter
// Purpose     : Parameterized enable-controlled counter for the RTL smoke flow.
// Clocks      : clk_i, rising edge, single domain; frequency is set by target constraints.
// Resets      : rst_ni, synchronous active-low reset sampled on clk_i.
// Interfaces  : enable_i controls updates; count_o is a registered output.
// Numeric     : Unsigned WIDTH-bit count, modulo 2**WIDTH; WIDTH defaults to 8.
// Latency     : An enabled update becomes visible after the sampling clock edge.
// Throughput  : One increment per enabled clock cycle.
// Invariants  : Reset clears count_o; disabled cycles hold its value.
// Generated   : no
`default_nettype none

module counter #(
    parameter int unsigned WIDTH = 8
) (
    input logic clk_i,
    input logic rst_ni,
    input logic enable_i,
    output logic [WIDTH-1:0] count_o
);
    always_ff @(posedge clk_i) begin
        if (!rst_ni) count_o <= '0;
        else if (enable_i) count_o <= count_o + 1'b1;
    end
endmodule

`default_nettype wire
