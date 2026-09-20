`default_nettype none

// Module       : axi_stream_assertions
// Purpose      : Bindable AXI-Stream source-side protocol assertions.
// Clocks       : aclk_i.
// Resets       : areset_ni, synchronous assertion disable, active low.
// Interfaces   : TVALID/TREADY/TDATA/TLAST observation only.
// Numeric      : TDATA is an uninterpreted DATA_WIDTH-bit payload.
// Latency      : No DUT latency assumption.
// Throughput   : One transfer per aclk_i when TVALID and TREADY are high.
// Invariants   : Payload is stable under backpressure; TLAST requires TVALID.
// Generated    : false; maintained verification template.
module axi_stream_assertions #(
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned MAX_STALL_CYCLES = 64
) (
    input wire                  aclk_i,
    input wire                  areset_ni,
    input wire                  tvalid_i,
    input wire                  tready_i,
    input wire [DATA_WIDTH-1:0] tdata_i,
    input wire                  tlast_i
);

`ifndef SYNTHESIS
    localparam int unsigned STALL_WIDTH = $clog2(MAX_STALL_CYCLES + 2);
    logic [STALL_WIDTH-1:0] stall_count_q;

    always_ff @(posedge aclk_i) begin
        if (!areset_ni || tready_i || !tvalid_i) begin
            stall_count_q <= '0;
        end else if (stall_count_q <= STALL_WIDTH'(MAX_STALL_CYCLES)) begin
            stall_count_q <= stall_count_q + 1'b1;
        end
    end

    axis_payload_stable_p: assert property (
        @(posedge aclk_i) disable iff (!areset_ni)
        tvalid_i && !tready_i |=> tvalid_i && $stable({tdata_i, tlast_i})
    );

    axis_tlast_requires_valid_p: assert property (
        @(posedge aclk_i) disable iff (!areset_ni)
        tlast_i |-> tvalid_i
    );

    axis_no_unknown_control_p: assert property (
        @(posedge aclk_i) disable iff (!areset_ni)
        !$isunknown({tvalid_i, tready_i, tlast_i})
    );

    axis_stall_bounded_p: assert property (
        @(posedge aclk_i) disable iff (!areset_ni)
        stall_count_q <= STALL_WIDTH'(MAX_STALL_CYCLES)
    );
`endif

endmodule

`default_nettype wire
