// VibeSilicon Module Contract v1
// Module      : readable_counter
// Purpose     : Exercise the deterministic readability gate.
// Clocks      : clk_i, 100 MHz, single domain.
// Resets      : rst_ni, asynchronous assert and synchronous release.
// Interfaces  : enable input and registered count output.
// Numeric     : unsigned 8-bit, wrap on overflow.
// Latency     : fixed 1 cycle.
// Throughput  : one update per cycle.
// Invariants  : count_q changes only on clk_i.
// Generated   : no

`default_nettype none
module readable_counter (
    input  logic       clk_i,
    input  logic       rst_ni,
    input  logic       enable_i,
    output logic [7:0] count_o
);
    logic [7:0] count_d;
    logic [7:0] count_q;

    always_comb begin
        count_d = count_q;
        if (enable_i) begin
            count_d = count_q + 8'd1;
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) count_q <= 8'h00;
        else count_q <= count_d;
    end

    assign count_o = count_q;
endmodule
`default_nettype wire
